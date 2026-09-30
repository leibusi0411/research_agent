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


class _KeyedEmbeddingClient:
    """Deterministic embeddings: one-hot-ish vectors keyed by a token in the text."""

    def embed(self, texts):
        vectors = []
        for text in texts:
            vec = [0.0] * 8
            for word in text.lower().split():
                # Deterministic across processes (hash() is salted).
                vec[sum(ord(c) for c in word) % 8] += 1.0
            vectors.append(vec)
        return vectors


class _ScriptedChatModel:
    """Returns queued replies in order; records every prompt."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


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
        embedding_client_factory=lambda _config: _KeyedEmbeddingClient(),
    )
    return TestClient(app), workspace


def _write_task_with_source_text(workspace: Path) -> str:
    """A completed task whose source has original fetched text on disk (R-285)."""
    task_id = _write_completed_web_task(workspace)
    task_dir = workspace / "tasks" / task_id
    texts_dir = task_dir / "artifacts" / "source_texts"
    texts_dir.mkdir(parents=True, exist_ok=True)
    import hashlib

    digest = hashlib.sha1("https://example.com/ckpt".encode("utf-8")).hexdigest()[:16]
    (texts_dir / f"{digest}.txt").write_text(
        "SqliteSaver writes every superstep to disk. " * 40, encoding="utf-8"
    )
    return task_id


def test_chat_import_indexes_source_text_and_retrieves_it(tmp_path):
    """R-285: importing a source with original fetched text builds a
    task-local index and retrieved excerpts reach the chat prompt."""
    chat_model = _RecordingChatModel()
    client, workspace = _chat_client(tmp_path, chat_model)
    task_id = _write_task_with_source_text(workspace)

    sent = client.post(
        f"/api/tasks/{task_id}/chat",
        json={"message": "What does SqliteSaver write?", "selected_sources": ["src_2"]},
    )

    assert sent.status_code == 200
    # Task-local index exists in the task dir (isolated from the global KB).
    index_dir = workspace / "tasks" / task_id / "chat_index"
    assert (index_dir / "fts.sqlite").exists()
    assert (index_dir / "chroma").exists()
    # The retrieved original text (not just metadata) reached the prompt.
    assert "SqliteSaver writes every superstep to disk." in chat_model.prompts[0]
    assert "[Imported sources" in chat_model.prompts[0]


def test_chat_import_is_incremental_across_calls(tmp_path):
    """R-285: re-importing the same source does not re-index it; a new source
    adds its own entry (append-only)."""
    chat_model = _RecordingChatModel()
    client, workspace = _chat_client(tmp_path, chat_model)
    task_id = _write_task_with_source_text(workspace)

    client.post(f"/api/tasks/{task_id}/chat", json={"message": "q1", "selected_sources": ["src_2"]})
    client.post(f"/api/tasks/{task_id}/chat", json={"message": "q2", "selected_sources": ["src_2"]})

    imports_path = workspace / "tasks" / task_id / "chat_index" / "imports.json"
    imports = json.loads(imports_path.read_text(encoding="utf-8"))
    assert list(imports["sources"].keys()) == ["src_2"]  # built once, reused


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


def test_chat_empty_selection_means_no_source_grounding(tmp_path):
    """R-283: explicit [] imports nothing — sources/findings stay out of the
    prompt (only summary + sections remain). Absent field keeps full grounding
    (backward compat with the old select-all semantics)."""
    chat_model = _RecordingChatModel()
    client, workspace = _chat_client(tmp_path, chat_model)
    task_id = _write_completed_web_task(workspace)

    client.post(f"/api/tasks/{task_id}/chat", json={"message": "q", "selected_sources": []})
    client.post(f"/api/tasks/{task_id}/chat", json={"message": "q"})

    empty_prompt = chat_model.prompts[0]
    assert "Sources:" not in empty_prompt
    assert "LangGraph models agents as state machines." not in empty_prompt
    full_prompt = chat_model.prompts[1]
    assert "LangGraph models agents as state machines." in full_prompt


def test_chat_import_cap_fifty_sources(tmp_path):
    """R-283: more than 50 imported sources is rejected with config_invalid."""
    chat_model = _RecordingChatModel()
    client, workspace = _chat_client(tmp_path, chat_model)
    task_id = _write_completed_web_task(workspace)
    # Widen the stored source list beyond the cap.
    result_path = workspace / "tasks" / task_id / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    base = result["curator_output"]["sources"][0]
    result["curator_output"]["sources"] = [
        {**base, "source_id": f"src_{i}"} for i in range(60)
    ]
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    rejected = client.post(
        f"/api/tasks/{task_id}/chat",
        json={"message": "q", "selected_sources": [f"src_{i}" for i in range(51)]},
    )

    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "config_invalid"
    assert "50" in rejected.json()["error"]["message"]
    assert chat_model.prompts == []


def test_chat_grounds_on_report_sections_when_present(tmp_path):
    """R-277: sectioned report chapters are part of the chat grounding context."""
    chat_model = _RecordingChatModel()
    client, workspace = _chat_client(tmp_path, chat_model)
    task_id = _write_completed_web_task(workspace)
    # Add sections to the stored result, as post-R-277 curators do.
    result_path = workspace / "tasks" / task_id / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["curator_output"]["sections"] = [
        {"heading": "Overview", "text": "RAG pipelines retrieve then generate."},
    ]
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    sent = client.post(f"/api/tasks/{task_id}/chat", json={"message": "Summarize the overview."})

    assert sent.status_code == 200
    assert "RAG pipelines retrieve then generate." in chat_model.prompts[0]
    assert "Overview" in chat_model.prompts[0]


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


def test_chat_system_prompt_allows_own_knowledge_and_search(tmp_path):
    """R-292: grounded-but-combining — own knowledge allowed (separated),
    SEARCH: requery protocol advertised."""
    chat_model = _RecordingChatModel()
    client, workspace = _chat_client(tmp_path, chat_model)
    task_id = _write_completed_web_task(workspace)

    client.post(f"/api/tasks/{task_id}/chat", json={"message": "q"})

    prompt = chat_model.prompts[0]
    assert "own knowledge" in prompt
    assert "SEARCH:" in prompt


def test_chat_search_loop_retrieves_more_excerpts(tmp_path):
    """R-292: the model may request more evidence via SEARCH: — the next
    prompt carries fresh excerpts and the final reply is persisted."""
    chat_model = _ScriptedChatModel([
        "SEARCH: checkpoint disk persistence",
        "SqliteSaver writes every superstep to disk. [S1]",
    ])
    client, workspace = _chat_client(tmp_path, chat_model)
    task_id = _write_task_with_source_text(workspace)

    sent = client.post(
        f"/api/tasks/{task_id}/chat",
        json={"message": "How are checkpoints persisted?", "selected_sources": ["src_2"]},
    )

    assert sent.status_code == 200
    assert sent.json()["reply"] == "SqliteSaver writes every superstep to disk. [S1]"
    assert len(chat_model.prompts) == 2
    # The requery round's prompt carries the retrieved original text.
    assert "SqliteSaver writes every superstep" in chat_model.prompts[1]
    # Intermediate SEARCH round is not persisted — only the final reply is.
    history = client.get(f"/api/tasks/{task_id}/chat").json()["messages"]
    assert [m["content"] for m in history][-1] == "SqliteSaver writes every superstep to disk. [S1]"


def test_chat_search_loop_caps_at_two_requests(tmp_path):
    """R-292: a model that keeps asking SEARCH forever gets cut off at the
    third call and must answer with what it has."""
    chat_model = _ScriptedChatModel([
        "SEARCH: one",
        "SEARCH: two",
        "SEARCH: three",
        "should never be reached",
    ])
    client, workspace = _chat_client(tmp_path, chat_model)
    task_id = _write_task_with_source_text(workspace)

    sent = client.post(
        f"/api/tasks/{task_id}/chat", json={"message": "q", "selected_sources": ["src_2"]}
    )

    assert sent.status_code == 200
    # R-293: the third SEARCH hits the per-kind cap; a budget note is injected
    # and the model's next output becomes the final reply.
    assert sent.json()["reply"] == "should never be reached"
    assert len(chat_model.prompts) == 4  # 1 initial + 2 executed + 1 refused round


# ---------------------------------------------------------------------------
# R-293: in-chat evidence actions (WEB / READ / LOCAL)
# ---------------------------------------------------------------------------


class _FakeGateway:
    """Records tool calls; returns queued results."""

    def __init__(self, results: list) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict]] = []

    def call(self, workflow: str, function_call: dict):
        self.calls.append((workflow, dict(function_call)))
        return self.results.pop(0)


class _FakeLocalRetriever:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def __call__(self, query: str) -> list:
        self.queries.append(query)
        from research_agent.web.schemas import PriorKnowledgeChunk

        return [PriorKnowledgeChunk(text="Local note about rerankers.", source_path="notes/rerank.md", heading_path=["RAG"])]


def _chat_client_with_tools(tmp_path, chat_model, gateway, retriever):
    """Configured app whose chat routes carry the evidence toolbox."""
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

    from research_agent.core.chat import ChatToolbox

    toolbox = ChatToolbox(gateway=gateway, local_retriever=retriever)
    app = create_app(
        config_path=config_path,
        chat_model_factory=lambda _config: chat_model,
        embedding_client_factory=lambda _config: _KeyedEmbeddingClient(),
        chat_toolbox_factory=lambda: toolbox,
    )
    return TestClient(app), workspace


def _chat_client_with_tools_holder(tmp_path, holder, gateway, retriever):
    """Like _chat_client_with_tools but the chat model is swappable via holder["model"]."""
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

    from research_agent.core.chat import ChatToolbox

    app = create_app(
        config_path=config_path,
        chat_model_factory=lambda _config: holder["model"],
        embedding_client_factory=lambda _config: _KeyedEmbeddingClient(),
        chat_toolbox_factory=lambda: ChatToolbox(gateway=gateway, local_retriever=retriever),
    )
    return TestClient(app), workspace


def _tool_ok(data: dict):
    class _R:
        status = "ok"
        error = None
        message = ""

        def __init__(self, payload: dict) -> None:
            self.data = payload

    return _R(data)


def test_chat_web_action_runs_gateway_and_cites_evidence(tmp_path):
    chat_model = _ScriptedChatModel([
        "WEB: reranker latency tradeoffs",
        "Cross-encoders add 30-80ms latency. [W1]",
    ])
    gateway = _FakeGateway([_tool_ok({"results": [
        {"title": "Latency of rerankers", "url": "https://example.com/lat", "content": "Cross-encoders add 30-80ms."}
    ]})])
    client, workspace = _chat_client_with_tools(tmp_path, chat_model, gateway, _FakeLocalRetriever())
    task_id = _write_completed_web_task(workspace)

    sent = client.post(f"/api/tasks/{task_id}/chat", json={"message": "reranker 代价是什么？"})

    assert sent.status_code == 200
    assert sent.json()["reply"] == "Cross-encoders add 30-80ms latency. [W1]"
    assert gateway.calls[0][0] == "web_research"
    assert gateway.calls[0][1]["name"] == "web.search"
    # Evidence reached the second prompt and was persisted to the chat log.
    assert "Latency of rerankers" in chat_model.prompts[1]
    evidence_path = workspace / "tasks" / task_id / "chat_evidence.jsonl"
    assert evidence_path.exists()
    lines = [json.loads(l) for l in evidence_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines[0]["kind"] == "web"
    assert lines[0]["argument"] == "reranker latency tradeoffs"


def test_chat_read_action_picks_pdf_tool_by_suffix(tmp_path):
    chat_model = _ScriptedChatModel([
        "READ: https://example.com/paper.pdf",
        "The paper confirms it. [R1]",
    ])
    gateway = _FakeGateway([_tool_ok({"url": "https://example.com/paper.pdf", "text": "Confirmed by the study.", "page_count": 3})])
    client, workspace = _chat_client_with_tools(tmp_path, chat_model, gateway, _FakeLocalRetriever())
    task_id = _write_completed_web_task(workspace)

    sent = client.post(f"/api/tasks/{task_id}/chat", json={"message": "细节"})

    assert sent.status_code == 200
    assert gateway.calls[0][1]["name"] == "web.download_pdf"
    assert "Confirmed by the study." in chat_model.prompts[1]


def test_chat_local_action_queries_vault_retriever(tmp_path):
    chat_model = _ScriptedChatModel([
        "LOCAL: rerank 策略",
        "Your notes cover rerank strategies. [L1]",
    ])
    retriever = _FakeLocalRetriever()
    client, workspace = _chat_client_with_tools(tmp_path, chat_model, _FakeGateway([]), retriever)
    task_id = _write_completed_web_task(workspace)

    sent = client.post(f"/api/tasks/{task_id}/chat", json={"message": "我的笔记里有什么"})

    assert sent.status_code == 200
    assert retriever.queries == ["rerank 策略"]
    assert "Local note about rerankers." in chat_model.prompts[1]
    assert "notes/rerank.md" in chat_model.prompts[1]


def test_chat_evidence_actions_capped_per_kind(tmp_path):
    chat_model = _ScriptedChatModel([
        "WEB: one", "WEB: two", "WEB: three",
        "Budget exhausted answer.",
    ])
    gateway = _FakeGateway([_tool_ok({"results": [{"title": f"t{i}", "url": "https://e.com", "content": "c"}]}) for i in range(3)])
    client, workspace = _chat_client_with_tools(tmp_path, chat_model, gateway, _FakeLocalRetriever())
    task_id = _write_completed_web_task(workspace)

    sent = client.post(f"/api/tasks/{task_id}/chat", json={"message": "q"})

    assert sent.status_code == 200
    assert sent.json()["reply"] == "Budget exhausted answer."
    assert len(gateway.calls) == 2  # third WEB was refused by the per-kind cap


def test_chat_history_includes_prior_evidence_summaries(tmp_path):
    """Follow-up turns see earlier evidence actions as one-line summaries."""
    holder: dict = {"model": _ScriptedChatModel(["WEB: topic", "Answer one. [W1]"])}
    gateway = _FakeGateway([_tool_ok({"results": [{"title": "Evidence title", "url": "https://e.com", "content": "c"}]})])
    client, workspace = _chat_client_with_tools_holder(tmp_path, holder, gateway, _FakeLocalRetriever())
    task_id = _write_completed_web_task(workspace)

    client.post(f"/api/tasks/{task_id}/chat", json={"message": "first"})

    from research_agent.core.chat import TaskChatService

    summaries = TaskChatService(task_dir=workspace / "tasks" / task_id, chat_model=None)._load_evidence_summaries()
    assert summaries == ['web: "topic"']
    # A follow-up question through the same app sees the summary block.
    holder["model"] = _ScriptedChatModel(["Follow-up answer."])
    second = client.post(f"/api/tasks/{task_id}/chat", json={"message": "second question"})
    assert second.status_code == 200
    assert 'web: "topic"' in holder["model"].prompts[0]
