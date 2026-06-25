from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from research_agent.core.config import InitConfigRequest, load_user_config
from research_agent.core.errors import ResearchError
from research_agent.core.kb import KnowledgeBaseIndex
from research_agent.core.providers import (
    FakeChatModelClient,
    OpenAICompatibleChatModel,
    OpenAICompatibleEmbeddingModel,
    build_role_chat_model_config,
)
from research_agent.core.service import CoreService
from research_agent.core.workspace import Workspace
from research_agent.web.role_invocation import invoke_role_json


def init_config(tmp_path: Path) -> Path:
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
    return config_path


def test_openai_compatible_chat_adapter_reads_user_config(tmp_path):
    config = load_user_config(init_config(tmp_path))
    requests: list[dict] = []
    client = OpenAICompatibleChatModel.from_config(config.chat_model, post_json=lambda url, headers, payload: requests.append({"url": url, "headers": headers, "payload": payload}) or {"choices": [{"message": {"content": "ok"}}]})

    content = client.complete("hello")

    assert content == "ok"
    assert requests[0]["url"] == "https://models.example/v1/chat/completions"
    assert requests[0]["headers"]["Authorization"] == "Bearer chat-key"
    assert requests[0]["payload"]["model"] == "chat-model"


def test_openai_compatible_embedding_adapter_reads_user_config(tmp_path):
    config = load_user_config(init_config(tmp_path))
    requests: list[dict] = []
    client = OpenAICompatibleEmbeddingModel.from_config(
        config.embedding_model,
        post_json=lambda url, headers, payload: requests.append({"url": url, "headers": headers, "payload": payload}) or {"data": [{"embedding": [0.1, 0.2]}]},
    )

    embeddings = client.embed(["alpha"])

    assert embeddings == [[0.1, 0.2]]
    assert requests[0]["url"] == "https://embeddings.example/v1/embeddings"
    assert requests[0]["headers"]["Authorization"] == "Bearer embedding-key"
    assert requests[0]["payload"]["model"] == "embedding-model"


def test_role_chat_model_config_sections_fallback_to_global(tmp_path):
    config_path = init_config(tmp_path)
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        text
        + "\n[chat_model.planner]\n"
        + 'model = "planner-model"\n'
        + 'api_key = "planner-key"\n',
        encoding="utf-8",
    )
    config = load_user_config(config_path)

    planner = build_role_chat_model_config(config, "planner")
    executor = build_role_chat_model_config(config, "executor")

    assert planner.model == "planner-model"
    assert planner.api_key == "planner-key"
    assert planner.base_url == "https://models.example/v1"
    assert executor == config.chat_model


def test_role_invocation_repairs_invalid_schema_once_then_returns_value():
    client = FakeChatModelClient(["not json", '{"answer": "fixed"}'])

    value = invoke_role_json(
        role_name="planner",
        prompt="return json",
        target_schema="AnswerSchema",
        chat_model=client,
        validator=lambda payload: payload if isinstance(payload.get("answer"), str) else (_ for _ in ()).throw(ValueError("answer required")),
    )

    assert value == {"answer": "fixed"}
    assert len(client.prompts) == 2
    assert "not json" in client.prompts[1]
    assert "AnswerSchema" in client.prompts[1]


def test_role_invocation_fails_after_one_schema_repair_attempt():
    client = FakeChatModelClient(["not json", "still not json"])

    with pytest.raises(ResearchError) as error:
        invoke_role_json(
            role_name="supervisor",
            prompt="return json",
            target_schema="SupervisorOutput",
            chat_model=client,
            validator=lambda payload: payload,
        )

    assert error.value.code == "schema_validation_failed"
    assert len(client.prompts) == 2


def test_core_service_default_web_runtime_uses_chat_model_with_schema_repair(tmp_path):
    config_path = init_config(tmp_path)
    service = CoreService(default_workspace=tmp_path / "runtime", config_path=config_path)
    client = FakeChatModelClient([
        "not json",  # Planner initial attempt fails
        '{"research_title": "Title", "subtasks": [{"question": "Q"}]}',  # Planner repair succeeds
        '{"tool_calls": [{"name": "web.search", "arguments": {"query": "test", "max_results": 5}}]}',  # Executor tool plan
        '{"subtask_id": "st_1", "status": "completed", "findings": [{"finding_id": "f_1", "subtask_id": "st_1", "text": "Finding", "source_ids": ["src_1"]}], "sources": [{"source_id": "src_1", "title": "Source", "url": "https://example.com", "fetched_at": "2026-06-25T10:00:00Z"}], "failure_reason": null}',  # Executor synthesis
        '{"route": "curate", "reason": "Enough evidence.", "next_subtask_ids": [], "skip_subtask_ids": [], "plan_revision_request": null, "research_gaps": [], "saturation": true}',  # Supervisor
        '{"title": "Title", "summary": "Summary", "findings": [{"finding_id": "f_1", "subtask_id": "st_1", "text": "Finding", "source_ids": ["src_1"]}], "sources": [{"source_id": "src_1", "title": "Source", "url": "https://example.com", "fetched_at": "2026-06-25T10:00:00Z"}]}',  # Curator
    ])

    result = service.run_web_research("question", chat_model=client)

    assert result["status"] == "completed"
    assert result["curator_output"]["title"] == "Title"
    assert len(client.prompts) == 6  # Planner + repair + tool_plan + synthesis + supervisor + curator


def test_core_service_rebuild_uses_configured_embedding_adapter_by_default(tmp_path, monkeypatch):
    config_path = init_config(tmp_path)
    config = load_user_config(config_path)
    (config.workspace.knowledge_base_path / "note.md").write_text("# Topic\n\nAlpha beta gamma.", encoding="utf-8")
    embedding_client = RecordingEmbeddingClient()

    monkeypatch.setattr(
        OpenAICompatibleEmbeddingModel,
        "from_config",
        staticmethod(lambda model_config: embedding_client),
    )

    result = CoreService(default_workspace=config.workspace.default_workspace, config_path=config_path).rebuild_kb_index()

    assert result["status"] == "ready"
    assert embedding_client.inputs == [["Alpha beta gamma."]]


def test_kb_rebuild_uses_injected_embedding_client(tmp_path):
    config_path = init_config(tmp_path)
    config = load_user_config(config_path)
    (config.workspace.knowledge_base_path / "note.md").write_text("# Topic\n\nAlpha beta gamma.", encoding="utf-8")
    embedding_client = RecordingEmbeddingClient()

    result = KnowledgeBaseIndex(Workspace(config.workspace.default_workspace), config_path, embedding_client=embedding_client).rebuild()

    assert result["status"] == "ready"
    assert embedding_client.inputs == [["Alpha beta gamma."]]
    vector_path = config.workspace.default_workspace / "indexes" / "local" / "chroma" / "chroma.sqlite3"
    with sqlite3.connect(vector_path) as connection:
        stored = json.loads(connection.execute("SELECT embedding FROM embeddings").fetchone()[0])
    assert stored == [0.3, 0.4, 0.5]


class RecordingEmbeddingClient:
    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.inputs.append(texts)
        return [[0.3, 0.4, 0.5] for _text in texts]
