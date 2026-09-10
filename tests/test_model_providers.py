from __future__ import annotations

import json
import sqlite3
from typing import Any
from pathlib import Path

import pytest

from research_agent.core.config import InitConfigRequest, ModelConfig, load_user_config
from research_agent.core.errors import ResearchError
from research_agent.core.kb import KnowledgeBaseIndex
from research_agent.core.providers import (
    OpenAICompatibleChatModel,
    OpenAICompatibleEmbeddingModel,
    build_role_chat_model_config,
    _parse_llm_json,
)
from research_agent.core.service import CoreService
from research_agent.core.workspace import Workspace
from research_agent.web.role_invocation import invoke_role_json
from research_agent.core.providers import ToolCallResult


class _SequencedChatClient:
    def __init__(self, completions: list[str]) -> None:
        self._completions = list(completions)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        self.prompts.append(prompt)
        return self._completions.pop(0) if self._completions else ""

    def complete_tool(self, prompt: str, *, tool_name: str, tool_schema: dict[str, Any]) -> ToolCallResult:
        raw = self.complete(prompt, json_mode=True)
        return ToolCallResult(name=tool_name, arguments=json.loads(raw))


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

    content = client.complete("hello", json_mode=True)

    assert content == "ok"
    assert requests[0]["url"] == "https://models.example/v1/chat/completions"
    assert requests[0]["headers"]["Authorization"] == "Bearer chat-key"
    assert requests[0]["payload"]["model"] == "chat-model"
    assert requests[0]["payload"]["temperature"] == 0.1
    assert requests[0]["payload"]["max_tokens"] == 16384
    assert requests[0]["payload"]["response_format"] == {"type": "json_object"}


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


def test_parse_llm_json_invalid_input_raises_value_error_not_runtime_error():
    with pytest.raises(ValueError, match="invalid JSON"):
        _parse_llm_json("{not json")


def test_parse_llm_json_requires_object():
    with pytest.raises(ValueError, match="object"):
        _parse_llm_json("[1]")


def test_openai_compatible_chat_adapter_reads_legacy_function_call(tmp_path):
    config = load_user_config(init_config(tmp_path))
    client = OpenAICompatibleChatModel.from_config(
        config.chat_model,
        post_json=lambda _url, _headers, _payload: {
            "choices": [{
                "message": {
                    "function_call": {
                        "name": "executor_tool_plan",
                        "arguments": '{"tool_calls": [{"name": "web.search", "arguments": {"query": "agent"}}]}',
                    },
                },
            }],
        },
    )

    result = client.complete_tool(
        "prompt",
        tool_name="executor_tool_plan",
        tool_schema={"type": "object"},
    )

    assert result.name == "executor_tool_plan"
    assert result.arguments["tool_calls"][0]["arguments"]["query"] == "agent"


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


def test_role_invocation_uses_native_function_calling_and_validates():
    """invoke_role_json calls complete_tool and runs validator on the result."""
    client = _SequencedChatClient(['{"answer": "fixed"}'])

    value = invoke_role_json(
        role_name="planner",
        prompt="return json",
        tool_name="plan_output",
        tool_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
        chat_model=client,
        validator=lambda payload: payload if payload.get("answer") == "fixed" else (_ for _ in ()).throw(ValueError("bad answer")),
    )

    assert value == {"answer": "fixed"}
    assert len(client.prompts) == 1

def test_role_invocation_validator_rejects_invalid_data():
    """invoke_role_json still applies the validator after parsing."""
    client = _SequencedChatClient(['{"answer": 123}'])

    with pytest.raises(ResearchError) as error:
        invoke_role_json(
            role_name="planner",
            prompt="return json",
            tool_name="plan_output",
            tool_schema={"type": "object"},
            chat_model=client,
            validator=lambda payload: payload if isinstance(payload.get("answer"), str) else (_ for _ in ()).throw(ValueError("answer required")),
        )
    assert error.value.code == "schema_validation_failed"
    assert "answer required" in error.value.message


def test_role_invocation_llm_failure_uses_registered_error_code():
    """LLM call failures surface as llm_call_failed, not a ValueError for an
    unknown code (the code was raised here but missing from VALID_ERROR_CODES,
    which masked the real provider error and failed tasks opaquely)."""

    class _FailingChatClient:
        def complete_tool(self, **_kwargs):
            raise ConnectionError("provider unreachable")

    with pytest.raises(ResearchError) as error:
        invoke_role_json(
            role_name="planner",
            prompt="return json",
            tool_name="plan_output",
            tool_schema={"type": "object"},
            chat_model=_FailingChatClient(),
            validator=lambda payload: payload,
        )
    assert error.value.code == "llm_call_failed"
    assert "provider unreachable" in error.value.message


def test_core_service_default_web_runtime_uses_function_calling(tmp_path):
    config_path = init_config(tmp_path)
    service = CoreService(default_workspace=tmp_path / "runtime", config_path=config_path)
    client = _SequencedChatClient([
        '{"research_title": "Title", "subtasks": [{"question": "Q"}]}',  # Planner
        '{"tool_calls": [{"name": "web.search", "arguments": {"query": "test", "max_results": 5}}]}',  # Executor tool plan
        '{"subtask_id": "st_1", "status": "completed", "findings": [{"finding_id": "f_1", "subtask_id": "st_1", "text": "Finding", "source_ids": ["src_1"]}], "sources": [{"source_id": "src_1", "title": "Source", "url": "https://example.com", "fetched_at": "2026-06-25T10:00:00Z"}], "failure_reason": null}',  # Executor synthesis
        '{"route": "curate", "reason": "Enough evidence.", "next_subtask_ids": [], "skip_subtask_ids": [], "plan_revision_request": null, "research_gaps": [], "saturation": true}',  # Supervisor
        '{"title": "Title", "summary": "Summary", "findings": [{"finding_id": "f_1", "subtask_id": "st_1", "text": "Finding", "source_ids": ["src_1"]}], "sources": [{"source_id": "src_1", "title": "Source", "url": "https://example.com", "fetched_at": "2026-06-25T10:00:00Z"}]}',  # Curator
    ])

    result = service.run_web_research("question", chat_models={"planner": client, "executor": client, "supervisor": client, "curator": client})

    assert result["status"] == "completed"
    assert result["curator_output"]["title"] == "Title"
    assert len(client.prompts) == 5  # Planner + tool_plan + synthesis + supervisor + curator (no repair)


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
    # ADR-0049: the embedding input is the search text enriched with the heading path.
    assert embedding_client.inputs == [["[Topic]\nAlpha beta gamma."]]


def test_kb_rebuild_uses_injected_embedding_client(tmp_path):
    config_path = init_config(tmp_path)
    config = load_user_config(config_path)
    (config.workspace.knowledge_base_path / "note.md").write_text("# Topic\n\nAlpha beta gamma.", encoding="utf-8")
    embedding_client = RecordingEmbeddingClient()

    result = KnowledgeBaseIndex(Workspace(config.workspace.default_workspace), config_path, embedding_client=embedding_client).rebuild()

    assert result["status"] == "ready"
    # ADR-0049: the embedding input is the search text enriched with the heading path.
    assert embedding_client.inputs == [["[Topic]\nAlpha beta gamma."]]
    # Verify embeddings were stored via ChromaStore API (not raw SQLite)
    from research_agent.core.chroma_store import ChromaStore
    store = ChromaStore(config.workspace.default_workspace / "indexes" / "chroma")
    assert store.count() == result["chunk_count"]


class RecordingEmbeddingClient:
    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.inputs.append(texts)
        return [[0.3, 0.4, 0.5] for _text in texts]


def test_complete_tool_reports_truncation_instead_of_json_error():
    """Reasoning models share the max_tokens budget between reasoning and
    content; a truncated answer must surface finish_reason=length instead of
    a bare 'LLM returned invalid JSON' so users can tell why parsing failed."""
    client = OpenAICompatibleChatModel.from_config(
        ModelConfig(provider="openai_compatible", base_url="https://api.example/v1", api_key="k", model="m"),
        post_json=lambda _url, _headers, _payload: {
            "choices": [
                {
                    "message": {"content": '{"research_title": "trunc"}'},
                    "finish_reason": "length",
                }
            ]
        },
    )
    with pytest.raises(ValueError, match="finish_reason=length"):
        client.complete_tool(prompt="plan", tool_name="plan_output", tool_schema={"type": "object"})


class _FlakyThenOkChatClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete_tool(self, prompt: str, *, tool_name: str, tool_schema: dict[str, Any]) -> ToolCallResult:
        self.calls += 1
        if self.calls == 1:
            raise ValueError("LLM returned invalid JSON: {broken")
        return ToolCallResult(name=tool_name, arguments={"ok": True})


def test_role_invocation_retries_once_after_parse_failure():
    client = _FlakyThenOkChatClient()
    result = invoke_role_json(
        role_name="planner_revision",
        prompt="revise",
        tool_name="plan_output",
        tool_schema={"type": "object"},
        chat_model=client,
        validator=lambda payload: payload,
    )
    assert result == {"ok": True}
    assert client.calls == 2


class _AlwaysFailingChatClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete_tool(self, prompt: str, *, tool_name: str, tool_schema: dict[str, Any]) -> ToolCallResult:
        self.calls += 1
        raise ValueError(f"LLM returned invalid JSON: attempt {self.calls}")


def test_role_invocation_raises_after_retry_is_exhausted():
    client = _AlwaysFailingChatClient()
    with pytest.raises(ResearchError) as error:
        invoke_role_json(
            role_name="planner_revision",
            prompt="revise",
            tool_name="plan_output",
            tool_schema={"type": "object"},
            chat_model=client,
            validator=lambda payload: payload,
        )
    assert error.value.code == "llm_call_failed"
    assert client.calls == 2


def test_normalize_tool_call_payload_collects_flattened_arguments():
    """Some models flatten arguments into the tool-call object instead of
    nesting them (seen with DeepSeek v4 in a real run) — the normalizer must
    collect the remaining keys as arguments so the gateway can validate."""
    from research_agent.web.executor import _normalize_tool_call_payload

    normalized = _normalize_tool_call_payload(
        {"name": "web.search", "query": "What is Python's GIL?", "max_results": 5}
    )
    tool_call = normalized["tool_calls"][0]
    assert tool_call["name"] == "web.search"
    assert tool_call["arguments"]["query"] == "What is Python's GIL?"
    assert tool_call["arguments"]["max_results"] == 5
