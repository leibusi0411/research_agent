"""Service-wiring tests for Prior Knowledge injection (ADR-0046).

Seam under test: ``research_agent.core.service.build_local_retriever`` —
the factory that decides whether a Web Research run gets a local
Knowledge Base retriever, and that the retriever returns hybrid-retrieval
chunks as ``PriorKnowledgeChunk`` items.
"""
from __future__ import annotations

from pathlib import Path

from research_agent.core.config import InitConfigRequest, load_user_config
from research_agent.core.service import CoreService, build_local_retriever


class _FixedEmbeddingClient:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _text in texts]


def configured_service(tmp_path: Path) -> tuple[CoreService, Path, Path, Path]:
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
    return service, config_path, workspace, vault


def test_build_local_retriever_returns_kb_chunks_when_index_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_AGENT_OFFLINE", "1")  # FTS5-only, no embedding network
    service, config_path, workspace, vault = configured_service(tmp_path)
    (vault / "langgraph.md").write_text(
        "# LangGraph\n\nLangGraph orchestrates agents with a state graph.", encoding="utf-8"
    )
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    retriever = build_local_retriever(config=load_user_config(config_path), config_path=config_path, workspace=service.workspace)

    assert retriever is not None
    chunks = retriever("state graph")
    assert len(chunks) == 1
    assert "state graph" in chunks[0].text
    assert chunks[0].source_path.endswith("langgraph.md")


def test_build_local_retriever_returns_none_when_disabled_in_config(tmp_path):
    service, config_path, workspace, vault = configured_service(tmp_path)
    (vault / "note.md").write_text("# Note\n\nContent.", encoding="utf-8")
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())
    content = config_path.read_text(encoding="utf-8").replace(
        "inject_local_context = true",
        "inject_local_context = false",
    )
    config_path.write_text(content, encoding="utf-8")
    assert load_user_config(config_path).research.inject_local_context is False

    retriever = build_local_retriever(config=load_user_config(config_path), config_path=config_path, workspace=service.workspace)

    assert retriever is None


def test_build_local_retriever_returns_none_when_index_missing(tmp_path):
    service, config_path, workspace, vault = configured_service(tmp_path)

    retriever = build_local_retriever(config=load_user_config(config_path), config_path=config_path, workspace=service.workspace)

    assert retriever is None


def test_build_local_retriever_works_with_stale_index(tmp_path, monkeypatch):
    """A stale index (FTS5 fresh, vectors outdated) still provides Prior Knowledge."""
    monkeypatch.setenv("RESEARCH_AGENT_OFFLINE", "1")
    service, config_path, workspace, vault = configured_service(tmp_path)
    note = vault / "langgraph.md"
    note.write_text("# LangGraph\n\nLangGraph orchestrates agents with a state graph.", encoding="utf-8")
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())
    note.write_text(
        "# LangGraph\n\nLangGraph orchestrates agents with a state graph. Extra content.",
        encoding="utf-8",
    )
    assert service.get_kb_status()["status"] == "stale"

    retriever = build_local_retriever(config=load_user_config(config_path), config_path=config_path, workspace=service.workspace)

    assert retriever is not None
    assert retriever("state graph")
