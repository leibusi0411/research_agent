"""Chat-over-research API (ADR-0050): NotebookLM-style Q&A on a finished task.

Seam under test: the public HTTP surface
  POST /api/tasks/{task_id}/chat  — ask a question, get a grounded reply
  GET  /api/tasks/{task_id}/chat  — reload persisted conversation history

The chat model is injected as a fake so tests assert grounding (the prompt
contains the task's findings/sources) without any network call.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from research_agent.api.app import create_app
from research_agent.core.config import InitConfigRequest
from research_agent.core.ids import generate_task_id, utc_now_iso
from research_agent.core.service import CoreService


class _RecordingChatModel:
    """Fake chat model that records every prompt and echoes a fixed reply."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        self.prompts.append(prompt)
        return "Grounded answer."


def _chat_client(tmp_path: Path, chat_model: _RecordingChatModel) -> tuple[TestClient, Path]:
    config_path = tmp_path / "config.toml"
    workspace = tmp_path / "runtime"
    vault = tmp_path / "vault"
    vault.mkdir()
    service = CoreService(default_workspace=workspace, config_path=config_path)
    service.init_config(
        InitConfigRequest(
            default_workspace=workspace,
            knowledge_base_path=vault,
            chat_base_url="https://models.example/v1",
            chat_api_key="chat-key",
            chat_model="chat-model",
            embedding_base_url="https://embeddings.example/v1",
            embedding_api_key="embedding-key",
            embedding_model="embedding-model",
            search_api_key="search-key",
        )
    )
    app = create_app(
        config_path=config_path,
        chat_model_factory=lambda _config: chat_model,
    )
    return TestClient(app), workspace


def _write_completed_web_task(workspace: Path) -> str:
    task_id = generate_task_id()
    now = utc_now_iso()
    task_dir = workspace / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "task_id": task_id,
        "mode": "web",
        "question": "What is LangGraph?",
        "status": "completed",
        "created_at": now,
        "curator_output": {
            "title": "LangGraph",
            "summary": "LangGraph is a graph orchestration framework.",
            "findings": [
                {"finding_id": "f_1", "subtask_id": "st_1", "text": "LangGraph models agents as state machines.", "source_ids": ["src_1"]},
                {"finding_id": "f_2", "subtask_id": "st_2", "text": "SqliteSaver persists checkpoints on disk.", "source_ids": ["src_2"]},
            ],
            "sources": [
                {"source_id": "src_1", "title": "LangGraph docs", "url": "https://example.com/lg", "fetched_at": now},
                {"source_id": "src_2", "title": "Checkpointing guide", "url": "https://example.com/ckpt", "fetched_at": now},
            ],
        },
    }
    (task_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return task_id


def test_chat_message_returns_grounded_reply_and_persists_history(tmp_path):
    chat_model = _RecordingChatModel()
    client, workspace = _chat_client(tmp_path, chat_model)
    task_id = _write_completed_web_task(workspace)

    sent = client.post(f"/api/tasks/{task_id}/chat", json={"message": "How does checkpointing work?"})

    assert sent.status_code == 200
    assert sent.json()["reply"] == "Grounded answer."
    # Grounding: the model saw the task's research, not just the question.
    assert len(chat_model.prompts) == 1
    assert "LangGraph models agents as state machines." in chat_model.prompts[0]
    assert "SqliteSaver persists checkpoints on disk." in chat_model.prompts[0]
    assert "How does checkpointing work?" in chat_model.prompts[0]

    history = client.get(f"/api/tasks/{task_id}/chat")
    assert history.status_code == 200
    messages = history.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "How does checkpointing work?"
    assert messages[1]["content"] == "Grounded answer."


def test_chat_selected_sources_narrow_the_grounding_context(tmp_path):
    chat_model = _RecordingChatModel()
    client, workspace = _chat_client(tmp_path, chat_model)
    task_id = _write_completed_web_task(workspace)

    sent = client.post(
        f"/api/tasks/{task_id}/chat",
        json={"message": "Tell me about state machines.", "selected_sources": ["src_1"]},
    )

    assert sent.status_code == 200
    prompt = chat_model.prompts[0]
    assert "LangGraph models agents as state machines." in prompt
    assert "LangGraph docs" in prompt
    # The unselected source and its finding stay out of the context.
    assert "SqliteSaver persists checkpoints on disk." not in prompt
    assert "Checkpointing guide" not in prompt


def test_chat_second_turn_replays_prior_conversation_into_the_prompt(tmp_path):
    chat_model = _RecordingChatModel()
    client, workspace = _chat_client(tmp_path, chat_model)
    task_id = _write_completed_web_task(workspace)

    client.post(f"/api/tasks/{task_id}/chat", json={"message": "First question."})
    client.post(f"/api/tasks/{task_id}/chat", json={"message": "Second question."})

    assert len(chat_model.prompts) == 2
    second_prompt = chat_model.prompts[1]
    assert "User: First question." in second_prompt
    assert "Assistant: Grounded answer." in second_prompt
    # The fresh question is asked after the replayed history, not inside it.
    assert second_prompt.rindex("Second question.") > second_prompt.rindex("Assistant: Grounded answer.")


def test_chat_errors_task_missing_blank_message_and_unconfigured(tmp_path):
    chat_model = _RecordingChatModel()
    client, workspace = _chat_client(tmp_path, chat_model)
    task_id = _write_completed_web_task(workspace)

    missing = client.post("/api/tasks/task_20990101_000000_abcdef/chat", json={"message": "hi"})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "task_not_found"

    blank = client.post(f"/api/tasks/{task_id}/chat", json={"message": "   "})
    assert blank.status_code == 400
    assert blank.json()["error"]["code"] == "config_invalid"

    missing_history = client.get("/api/tasks/task_20990101_000000_abcdef/chat")
    assert missing_history.status_code == 404
    assert missing_history.json()["error"]["code"] == "task_not_found"

    # Unconfigured instance: chat, like research, needs a chat model.
    unconfigured = TestClient(create_app(config_path=tmp_path / "none.toml"))
    denied = unconfigured.post(f"/api/tasks/{task_id}/chat", json={"message": "hi"})
    assert denied.status_code == 400
    assert denied.json()["error"]["code"] == "config_missing"


def test_chat_rejects_unfinished_tasks(tmp_path):
    chat_model = _RecordingChatModel()
    client, workspace = _chat_client(tmp_path, chat_model)
    task_id = generate_task_id()
    task_dir = workspace / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    # result.json exists from task creation with status "running".
    (task_dir / "result.json").write_text(
        json.dumps({"task_id": task_id, "mode": "web", "question": "q", "status": "running"}), encoding="utf-8"
    )

    rejected = client.post(f"/api/tasks/{task_id}/chat", json={"message": "hi"})

    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "runtime_error"
    assert "not finished" in rejected.json()["error"]["message"]
    # The model was never called and nothing was persisted.
    assert chat_model.prompts == []
    assert not (task_dir / "chat.jsonl").exists()
