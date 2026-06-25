from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from research_agent.core.config import InitConfigRequest
from research_agent.core.service import CoreService
from research_agent.core.tasks import TaskRecord
from tests.fakes import FixedEmbeddingClient


def configured_env_with_ready_index(tmp_path: Path) -> tuple[dict[str, str], Path]:
    config_path = tmp_path / "config.toml"
    workspace = tmp_path / "runtime"
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# LangGraph\n\nLocal planner executor supervisor content.", encoding="utf-8")
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
    service.rebuild_kb_index(embedding_client=FixedEmbeddingClient())
    env = os.environ.copy()
    env["RESEARCH_AGENT_CONFIG_PATH"] = str(config_path)
    src_path = str(Path(__file__).resolve().parents[1] / "src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not existing_pythonpath else os.pathsep.join([src_path, existing_pythonpath])
    env["RESEARCH_AGENT_FAKE_WEB"] = "1"  # CLI subprocess must use fake runtime for offline tests
    return env, workspace


def run_cli(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "research_agent.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_both_cli_runs_local_and_web_as_separate_finished_tasks(tmp_path):
    env, workspace = configured_env_with_ready_index(tmp_path)

    result = run_cli(env, "both", "planner supervisor")

    assert result.returncode == 0
    assert "Local Results" in result.stdout
    assert "Web Summary" in result.stdout
    assert "Web report_path:" in result.stdout
    rows = task_rows(workspace)
    assert sorted(row[1] for row in rows) == ["local", "web"]
    assert {row[2] for row in rows} == {"completed"}


def test_both_cli_exits_nonzero_when_web_report_write_fails_but_keeps_separate_results(tmp_path):
    env, workspace = configured_env_with_ready_index(tmp_path)
    env["RESEARCH_AGENT_FAKE_WEB_REPORT_FAILURE"] = "1"

    result = run_cli(env, "both", "planner supervisor")

    assert result.returncode == 1
    assert "Local Results" in result.stdout
    assert "[web:file_write_error]" in result.stdout
    rows = task_rows(workspace)
    assert sorted((row[1], row[2]) for row in rows) == [("local", "completed"), ("web", "failed")]


def test_same_family_busy_conflict_does_not_block_other_family_in_both(tmp_path):
    env, workspace = configured_env_with_ready_index(tmp_path)
    lock_dir = workspace / "locks"
    lock_dir.mkdir(parents=True)
    (lock_dir / "local.lock").write_text(json.dumps({"task_id": "task_active_local"}), encoding="utf-8")

    local = run_cli(env, "local", "planner")
    both = run_cli(env, "both", "planner")

    assert local.returncode == 1
    assert "[busy]" in local.stdout
    assert both.returncode == 1
    assert "[local:busy]" in both.stdout
    assert "Web Summary" in both.stdout
    rows = task_rows(workspace)
    assert [(row[1], row[2]) for row in rows] == [("web", "completed")]


def test_task_list_displays_finished_tasks_sorted_by_created_at_desc(tmp_path):
    env, workspace = configured_env_with_ready_index(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=Path(env["RESEARCH_AGENT_CONFIG_PATH"]))
    service.task_store.upsert_finished_task(
        TaskRecord(
            task_id="task_20260624_100000_aaaaaa",
            mode="local",
            status="completed",
            title_or_question="older local",
            created_at="2026-06-24T10:00:00Z",
            completed_at="2026-06-24T10:00:01Z",
            report_path=None,
            result_path=str(workspace / "tasks" / "old" / "result.json"),
        )
    )
    service.task_store.upsert_finished_task(
        TaskRecord(
            task_id="task_20260624_110000_bbbbbb",
            mode="web",
            status="failed",
            title_or_question="newer web",
            created_at="2026-06-24T11:00:00Z",
            completed_at="2026-06-24T11:00:01Z",
            report_path=None,
            result_path=str(workspace / "tasks" / "new" / "result.json"),
        )
    )

    result = run_cli(env, "task", "list")

    assert result.returncode == 0
    assert "task_id" in result.stdout
    newer_index = result.stdout.index("task_20260624_110000_bbbbbb")
    older_index = result.stdout.index("task_20260624_100000_aaaaaa")
    assert newer_index < older_index
    assert "web" in result.stdout
    assert "failed" in result.stdout
    assert "newer web" in result.stdout


def task_rows(workspace: Path) -> list[tuple[str, str, str]]:
    with sqlite3.connect(workspace / "tasks.sqlite") as connection:
        return connection.execute("SELECT task_id, mode, status FROM tasks ORDER BY created_at DESC").fetchall()
