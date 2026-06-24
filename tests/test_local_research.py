import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from research_agent.core.config import InitConfigRequest
from research_agent.core.service import CoreService
from tests.fakes import FixedEmbeddingClient


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
    service.rebuild_kb_index(embedding_client=FixedEmbeddingClient())

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
    service.rebuild_kb_index(embedding_client=FixedEmbeddingClient())
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
    service.rebuild_kb_index(embedding_client=FixedEmbeddingClient())
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
