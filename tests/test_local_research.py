import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from research_agent.core.config import InitConfigRequest
from research_agent.core.service import CoreService


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


def test_local_research_returns_source_linked_results_and_persists_task(tmp_path):
    service, _config_path, workspace, vault = configured_service(tmp_path)
    note = vault / "langgraph.md"
    note.write_text(
        "# LangGraph\n\nLangGraph supports state graphs for planner executor supervisor research workflows.",
        encoding="utf-8",
    )
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    result = service.run_local_research("planner supervisor")

    assert result["status"] == "completed"
    assert result["mode"] == "local"
    assert result["local_results"]
    first = result["local_results"][0]
    assert "planner executor supervisor" in first["text"]
    assert first["source_path"] == str(note)
    assert first["heading_path"] == ["LangGraph"]
    assert "report_path" not in result
    assert list((workspace / "reports" / "web").glob("*.md")) == []

    task_dir = workspace / "tasks" / result["task_id"]
    assert json.loads((task_dir / "result.json").read_text(encoding="utf-8"))["local_results"][0]["source_path"] == str(note)
    with sqlite3.connect(workspace / "tasks.sqlite") as connection:
        row = connection.execute("SELECT mode, status, result_path FROM tasks WHERE task_id = ?", (result["task_id"],)).fetchone()
    assert row[0] == "local"
    assert row[1] == "completed"
    assert row[2].endswith("result.json")


def test_local_research_fails_before_retrieval_when_index_missing_or_stale(tmp_path):
    service, _config_path, workspace, vault = configured_service(tmp_path)

    missing = service.run_local_research("anything")

    assert missing["status"] == "failed"
    assert missing["error"]["code"] == "kb_index_missing"
    assert "kb rebuild" in missing["error"]["message"]

    (vault / "note.md").write_text("# Note\n\nInitial local content.", encoding="utf-8")
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())
    (vault / "note.md").write_text("# Note\n\nChanged local content.", encoding="utf-8")

    stale = service.run_local_research("Changed")

    assert stale["status"] == "failed"
    assert stale["error"]["code"] == "kb_index_stale"
    assert "kb rebuild" in stale["error"]["message"]
    with sqlite3.connect(workspace / "tasks.sqlite") as connection:
        statuses = connection.execute("SELECT status FROM tasks ORDER BY created_at").fetchall()
    assert statuses == [("failed",), ("failed",)]


def test_local_research_cli_success_and_failure_outputs(tmp_path):
    service, config_path, _workspace, vault = configured_service(tmp_path)
    (vault / "note.md").write_text("# CLI\n\nLocal CLI research content about graph planning.", encoding="utf-8")
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())
    env = os.environ.copy()
    env["RESEARCH_AGENT_CONFIG_PATH"] = str(config_path)
    env["RESEARCH_AGENT_PROVIDER_CALL_SENTINEL"] = "fail-if-read"

    success = subprocess.run(
        [sys.executable, "-m", "research_agent.cli", "local", "graph planning"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    (vault / "note.md").write_text("# CLI\n\nChanged content.", encoding="utf-8")
    failure = subprocess.run(
        [sys.executable, "-m", "research_agent.cli", "local", "changed"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert success.returncode == 0
    assert "Local Results" in success.stdout
    assert "source_path:" in success.stdout
    assert "Local CLI research content" in success.stdout
    assert failure.returncode == 1
    assert "[kb_index_stale]" in failure.stdout


# ---------------------------------------------------------------------------
# FTS5 + Chroma hybrid retrieval tests (R-13 / ChromaDB integration)
# ---------------------------------------------------------------------------


def test_fts5_keyword_retrieval_finds_relevant_chunks(tmp_path):
    """FTS5 MATCH should return ranked results scoped to query terms (R-13 fix)."""
    service, _config_path, workspace, vault = configured_service(tmp_path)
    (vault / "alice.md").write_text("# Alice\n\nAlice likes Python async programming.", encoding="utf-8")
    (vault / "bob.md").write_text("# Bob\n\nBob prefers Rust for systems programming.", encoding="utf-8")
    (vault / "carol.md").write_text("# Carol\n\nCarol writes async Python frameworks and tools.", encoding="utf-8")
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    result = service.run_local_research("async Python")

    assert result["status"] == "completed"
    texts = [item["text"] for item in result["local_results"]]
    assert any("async Python" in t or "async programming" in t for t in texts)
    # Bob's Rust article should NOT appear in top results
    if len(result["local_results"]) >= 2:
        assert not any("Rust" in t for t in texts[:2])


def test_fts5_retrieval_handles_special_characters(tmp_path):
    """FTS5 should sanitise special characters and still return results."""
    service, _config_path, workspace, vault = configured_service(tmp_path)
    (vault / "quotes.md").write_text("# Quotes\n\nHe said: \"Python's async is great for I/O.\"", encoding="utf-8")
    (vault / "cpp.md").write_text("# C++\n\nC++ supports both sync and async patterns via futures and coroutines.", encoding="utf-8")
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    result = service.run_local_research("Python's async")
    assert result["status"] == "completed"
    assert len(result["local_results"]) >= 1

    # FTS5 special characters like ++ and () should not cause errors
    result2 = service.run_local_research("C++ async")
    assert result2["status"] == "completed"
    assert len(result2["local_results"]) >= 1, "special chars should not break FTS5"


def test_hybrid_retrieval_with_embedding_client(tmp_path):
    """When embedding_client is provided, results combine FTS5 + Chroma via RRF."""
    service, _config_path, workspace, vault = configured_service(tmp_path)
    (vault / "semantic.md").write_text(
        "# Semantic\n\nVector embeddings capture semantic meaning across different wordings.",
        encoding="utf-8",
    )
    (vault / "keyword.md").write_text(
        "# Keyword\n\nFTS5 matches exact keywords like 'vector' and 'embedding' directly.",
        encoding="utf-8",
    )
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    # Use a simple embedding client that produces varied but deterministic vectors
    class VariedEmbeddingClient:
        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[float(hash(t) % 100) / 100.0 for _ in range(3)] for t in texts]

    result = service.run_local_research(
        "semantic meaning",
        embedding_client=VariedEmbeddingClient(),
    )

    assert result["status"] == "completed"
    assert len(result["local_results"]) >= 2


def test_fts5_only_fallback_works_without_embedding_client(tmp_path):
    """When no embedding_client is provided, retrieval should use FTS5 only."""
    service, _config_path, workspace, vault = configured_service(tmp_path)
    (vault / "note.md").write_text("# Note\n\nThis is about machine learning pipelines.", encoding="utf-8")
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    # No embedding_client passed → FTS5-only path
    result = service.run_local_research("machine learning")

    assert result["status"] == "completed"
    assert len(result["local_results"]) >= 1
    assert any("machine learning" in item["text"] for item in result["local_results"])


# ---------------------------------------------------------------------------
# P0 fix tests: R-57, R-58, R-59
# ---------------------------------------------------------------------------


def test_chroma_store_close_is_idempotent(tmp_path):
    """R-57: Calling close() twice should not raise."""
    from research_agent.core.chroma_store import ChromaStore

    store = ChromaStore(tmp_path / "chroma")
    store.close()
    store.close()  # second call should be a no-op


def test_chroma_store_build_index_after_close_reopens(tmp_path):
    """R-62: build_index() after close() should transparently re-open, not crash."""
    from research_agent.core.chroma_store import ChromaStore

    store = ChromaStore(tmp_path / "chroma")
    store.close()

    # Should not raise — ChromaStore transparently re-opens the client
    store.build_index([], None)

    # Clean up
    store.close()


def test_chroma_store_query_after_close_reopens(tmp_path):
    """R-62: query() after close() should transparently re-open, not crash."""
    from research_agent.core.chroma_store import ChromaStore

    store = ChromaStore(tmp_path / "chroma")
    store.close()

    # Should not crash — ChromaStore transparently re-opens the client
    result = store.query([0.1, 0.2, 0.3])
    assert result == []

    # Clean up
    store.close()


def test_chroma_store_count_returns_zero_after_close(tmp_path):
    """R-57: count() after close() should return 0."""
    from research_agent.core.chroma_store import ChromaStore

    store = ChromaStore(tmp_path / "chroma")
    store.close()

    assert store.count() == 0


def test_chroma_store_query_empty_collection(tmp_path):
    """R-58: query() on empty collection should return empty list."""
    from research_agent.core.chroma_store import ChromaStore

    store = ChromaStore(tmp_path / "chroma")
    store.build_index([], None)  # create empty collection

    assert store.query([0.1, 0.2, 0.3]) == []


def test_chroma_store_query_returns_results_with_metadata(tmp_path):
    """R-58: query() should correctly extract metadata fields."""
    from research_agent.core.chroma_store import ChromaStore

    store = ChromaStore(tmp_path / "chroma")

    class FakeChunk:
        def __init__(self, cid, text, path, heading, start, end):
            self.chunk_id = cid
            self.text = text
            self.source_path = path
            self.heading_path = heading
            self.start_offset = start
            self.end_offset = end

    chunks = [
        FakeChunk("c1", "hello world", "/doc.md", ["Intro"], 0, 11),
        FakeChunk("c2", "foo bar", "/doc.md", ["Section"], 12, 19),
    ]

    class FakeEmbedding:
        def embed(self, texts):
            return [[float(i), 0.0, 0.0] for i, _ in enumerate(texts)]

    store.build_index(chunks, FakeEmbedding())
    results = store.query([0.0, 0.0, 0.0], n_results=2)

    assert len(results) >= 1
    first = results[0]
    assert "chunk_id" in first
    assert "text" in first
    assert "source_path" in first
    assert "heading_path" in first
    assert "score" in first


def test_fts5_reserved_words_do_not_cause_operational_error(tmp_path):
    """R-59: AND, OR, NOT as standalone query terms should not break FTS5."""
    service, _config_path, workspace, vault = configured_service(tmp_path)
    (vault / "logic.md").write_text(
        "# Logic\n\nAND and OR are boolean operators. NOT is a negation operator.",
        encoding="utf-8",
    )
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    # Each reserved word as a standalone query
    for word in ("AND", "OR", "NOT"):
        result = service.run_local_research(word)
        assert result["status"] == "completed", f"FTS5 failed for reserved word: {word}"


def test_fts5_only_special_characters_returns_empty(tmp_path):
    """R-59: Query with only special characters should return empty, not error."""
    service, _config_path, workspace, vault = configured_service(tmp_path)
    (vault / "note.md").write_text("# Note\n\nSome content here.", encoding="utf-8")
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    result = service.run_local_research("**++()")
    assert result["status"] == "completed"
    assert result["local_results"] == []


def test_fts5_parentheses_in_query(tmp_path):
    """R-59: Parentheses in query like (async) should not cause errors."""
    service, _config_path, workspace, vault = configured_service(tmp_path)
    (vault / "async.md").write_text(
        "# Async\n\nThe async keyword enables asynchronous programming in Python.",
        encoding="utf-8",
    )
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    result = service.run_local_research("(async) programming")
    assert result["status"] == "completed"
    assert len(result["local_results"]) >= 1


def test_fts5_asterisk_in_query(tmp_path):
    """R-59: Asterisk * in query should be stripped, not treated as FTS5 wildcard."""
    service, _config_path, workspace, vault = configured_service(tmp_path)
    (vault / "glob.md").write_text(
        "# Glob\n\nWildcard patterns use star to match any sequence of characters.",
        encoding="utf-8",
    )
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    result = service.run_local_research("wildcard * match")
    assert result["status"] == "completed"
    assert len(result["local_results"]) >= 1


def test_fts5_mixed_reserved_and_normal_terms(tmp_path):
    """R-59: Mix of reserved words and normal terms should work correctly."""
    service, _config_path, workspace, vault = configured_service(tmp_path)
    (vault / "search.md").write_text(
        "# Search\n\nBoolean search uses AND OR NOT operators for filtering results.",
        encoding="utf-8",
    )
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    result = service.run_local_research("Boolean AND search")
    assert result["status"] == "completed"
    assert len(result["local_results"]) >= 1
