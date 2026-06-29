import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from research_agent.core.chroma_store import ChromaStore
from research_agent.core.config import InitConfigRequest
from research_agent.core.kb import KnowledgeBaseIndex
from research_agent.core.service import CoreService


class _FixedEmbeddingClient:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _text in texts]


def write_config(tmp_path: Path) -> tuple[Path, Path, Path]:
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
    return config_path, workspace, vault


def test_kb_status_is_missing_before_rebuild(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)

    status = CoreService(default_workspace=workspace, config_path=config_path).get_kb_status()

    assert status["status"] == "missing"
    assert status["vault_path"] == str(vault)
    assert status["file_count"] == 0
    assert status["chunk_count"] == 0


def test_kb_rebuild_parses_chunks_and_builds_indexes_read_only(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    note = vault / "LangGraph.md"
    original = """---
title: LangGraph Notes
tags: [research]
---
# Planner

Planner creates subtasks and writes them to the blackboard.

## Executor

Executor fetches sources. See [LangGraph](https://langchain-ai.github.io/langgraph/), [ADR](docs/adr/0026.md), and [[Local RAG]].
"""
    note.write_text(original, encoding="utf-8")
    (vault / "plain.txt").write_text("Plain text source paragraph.\n\nSecond paragraph.", encoding="utf-8")
    (vault / "page.html").write_text(
        "<html><body><nav>skip nav</nav><article><h1>HTML Title</h1><p>Extracted HTML content.</p></article></body></html>",
        encoding="utf-8",
    )

    result = CoreService(default_workspace=workspace, config_path=config_path).rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    assert result["status"] == "ready"
    assert result["file_count"] == 3
    assert result["chunk_count"] >= 3
    assert note.read_text(encoding="utf-8") == original
    assert (workspace / "indexes" / "local" / "fts.sqlite").is_file()
    assert (workspace / "indexes" / "chroma").is_dir()
    assert (workspace / "indexes" / "chroma" / "chroma.sqlite3").is_file()

    manifest = json.loads((workspace / "indexes" / "local" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "ready"
    assert manifest["vault_path"] == str(vault)
    assert {Path(file["path"]).name for file in manifest["files"]} == {"LangGraph.md", "plain.txt", "page.html"}
    md_record = next(file for file in manifest["files"] if file["path"].endswith("LangGraph.md"))
    assert md_record["frontmatter"]["title"] == "LangGraph Notes"
    assert md_record["title"] == "LangGraph Notes"
    assert md_record["headings"] == ["Planner", "Executor"]
    assert md_record["links"] == ["https://langchain-ai.github.io/langgraph/", "docs/adr/0026.md"]
    assert md_record["wikilinks"] == ["Local RAG"]

    with sqlite3.connect(workspace / "indexes" / "local" / "fts.sqlite") as connection:
        rows = connection.execute(
            "SELECT source_path, heading_path, text FROM chunks ORDER BY source_path, start_offset"
        ).fetchall()
    store = ChromaStore(workspace / "indexes" / "chroma")
    assert store.count() == manifest["chunk_count"]
    assert any("Planner creates subtasks" in row[2] for row in rows)
    assert any("Executor fetches sources" in row[2] for row in rows)
    assert any("Extracted HTML content" in row[2] for row in rows)
    assert any("Planner" in row[1] for row in rows)


def test_kb_status_detects_stale_files_by_mtime_and_size(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    note = vault / "note.md"
    note.write_text("# One\n\nOriginal paragraph.", encoding="utf-8")
    service = CoreService(default_workspace=workspace, config_path=config_path)
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    assert service.get_kb_status()["status"] == "ready"

    note.write_text("# One\n\nOriginal paragraph changed.", encoding="utf-8")

    assert service.get_kb_status()["status"] == "stale"


def test_kb_status_requires_vector_index_artifact(tmp_path, monkeypatch):
    config_path, workspace, vault = write_config(tmp_path)
    (vault / "note.md").write_text("# One\n\nOriginal paragraph.", encoding="utf-8")
    service = CoreService(default_workspace=workspace, config_path=config_path)
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    # ChromaDB holds file locks on Windows that prevent deletion.
    # Simulate a missing vector index by patching the vector_path property.
    monkeypatch.setattr(
        KnowledgeBaseIndex,
        "vector_path",
        property(lambda self: self.index_dir / "chroma" / "nonexistent.sqlite3"),
    )

    assert service.get_kb_status()["status"] == "failed"


def test_rebuild_failure_preserves_prior_index_as_stale(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    note = vault / "note.md"
    note.write_text("# One\n\nOriginal paragraph.", encoding="utf-8")
    service = CoreService(default_workspace=workspace, config_path=config_path)
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())
    prior_manifest = (workspace / "indexes" / "local" / "manifest.json").read_text(encoding="utf-8")
    note.write_text("# One\n\nChanged paragraph.", encoding="utf-8")

    failing_index = KnowledgeBaseIndex(service.workspace, service.config_path, fail_after_temp_build=True)
    result = failing_index.rebuild()

    assert result["status"] == "stale"
    assert "error" in result
    assert (workspace / "indexes" / "local" / "manifest.json").read_text(encoding="utf-8") == prior_manifest
    assert service.get_kb_status()["status"] == "stale"


def test_first_rebuild_failure_persists_failed_status(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    (vault / "note.md").write_text("# One\n\nOriginal paragraph.", encoding="utf-8")
    service = CoreService(default_workspace=workspace, config_path=config_path)

    result = KnowledgeBaseIndex(service.workspace, service.config_path, fail_after_temp_build=True).rebuild()

    assert result["status"] == "failed"
    assert service.get_kb_status()["status"] == "failed"


def test_building_marker_is_reported(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    building_marker = workspace / "indexes" / "local.building"
    building_marker.parent.mkdir(parents=True, exist_ok=True)
    building_marker.write_text("building", encoding="utf-8")

    assert service.get_kb_status()["status"] == "building"


def test_chunking_aggregates_paragraphs_and_hard_splits_large_blocks(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    short_paragraphs = "\n\n".join(f"paragraph {index}" for index in range(20))
    long_paragraph = "x" * 6000
    (vault / "large.md").write_text(f"# Large\n\n{short_paragraphs}\n\n{long_paragraph}", encoding="utf-8")

    CoreService(default_workspace=workspace, config_path=config_path).rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    with sqlite3.connect(workspace / "indexes" / "local" / "fts.sqlite") as connection:
        lengths = [row[0] for row in connection.execute("SELECT length(text) FROM chunks").fetchall()]

    assert any(length > 100 for length in lengths)
    assert max(lengths) <= 5000


def test_kb_cli_status_and_rebuild(tmp_path):
    from fastapi.testclient import TestClient
    from research_agent.api.app import create_app

    config_path, workspace, vault = write_config(tmp_path)
    (vault / "note.md").write_text("# CLI\n\nCLI rebuild content.", encoding="utf-8")

    client = TestClient(create_app(
        config_path=config_path,
        embedding_client_factory=lambda _config: _FixedEmbeddingClient(),
    ))

    before = client.get("/api/kb/status")
    assert before.json()["status"] == "missing"

    rebuild = client.post("/api/kb/rebuild")
    assert rebuild.json()["status"] == "ready"
    assert "chunk_count" in rebuild.json()

    after = client.get("/api/kb/status")
    assert after.json()["status"] == "ready"
