import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from research_agent.core.errors import ResearchError
from research_agent.core.ids import generate_task_id, utc_now_iso
from research_agent.core.service import CoreService
from research_agent.core.tasks import TaskRecord, TaskStore
from research_agent.core.workspace import Workspace


def test_task_id_and_timestamp_use_project_formats():
    now = datetime(2026, 6, 23, 10, 30, 0, tzinfo=timezone.utc)

    assert generate_task_id(now=now, suffix="a1b2c3") == "task_20260623_103000_a1b2c3"
    assert utc_now_iso(now) == "2026-06-23T10:30:00Z"


def test_invalid_task_id_is_rejected_before_file_or_database_writes(tmp_path):
    workspace = Workspace(tmp_path)

    with pytest.raises(ValueError, match="invalid task_id"):
        workspace.create_task_folder(
            "../outside",
            task_metadata={"task_id": "../outside", "mode": "local"},
            result={"status": "completed"},
        )

    store = TaskStore(tmp_path / "tasks.sqlite")
    with pytest.raises(ValueError, match="invalid task_id"):
        store.upsert_finished_task(
            TaskRecord(
                task_id="../outside",
                mode="local",
                status="completed",
                title_or_question="bad",
                created_at="2026-06-23T10:30:00Z",
                completed_at="2026-06-23T10:31:00Z",
                report_path=None,
                result_path="../outside/result.json",
            )
        )

    assert not (tmp_path.parent / "outside").exists()


def test_workspace_creation_uses_default_workspace_layout(tmp_path):
    workspace = Workspace(tmp_path)

    workspace.ensure()

    assert workspace.tasks_dir == tmp_path / "tasks"
    assert workspace.local_index_dir == tmp_path / "indexes" / "local"
    assert workspace.web_reports_dir == tmp_path / "reports" / "web"
    assert workspace.logs_dir == tmp_path / "logs"
    assert workspace.tasks_dir.is_dir()
    assert workspace.local_index_dir.is_dir()
    assert workspace.web_reports_dir.is_dir()
    assert workspace.logs_dir.is_dir()


def test_task_folder_can_store_task_result_events_and_artifacts(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.ensure()

    task_dir = workspace.create_task_folder(
        "task_20260623_103000_a1b2c3",
        task_metadata={"task_id": "task_20260623_103000_a1b2c3", "mode": "local"},
        result={"status": "completed", "local_results": []},
    )
    workspace.append_event("task_20260623_103000_a1b2c3", {"phase": "local_rag", "event_type": "started"})

    assert json.loads((task_dir / "task.json").read_text(encoding="utf-8"))["mode"] == "local"
    assert json.loads((task_dir / "result.json").read_text(encoding="utf-8"))["status"] == "completed"
    assert (task_dir / "events.jsonl").read_text(encoding="utf-8").strip() == (
        '{"phase":"local_rag","event_type":"started"}'
    )
    assert (task_dir / "artifacts" / "web_sources").is_dir()


def test_task_store_persists_finished_tasks_for_local_and_web_only(tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite")
    store.initialize()

    store.upsert_finished_task(
        TaskRecord(
            task_id="task_20260623_103000_a1b2c3",
            mode="local",
            status="completed",
            title_or_question="question one",
            created_at="2026-06-23T10:30:00Z",
            completed_at="2026-06-23T10:31:00Z",
            report_path=None,
            result_path="tasks/task_20260623_103000_a1b2c3/result.json",
        )
    )
    store.upsert_finished_task(
        TaskRecord(
            task_id="task_20260623_104000_d4e5f6",
            mode="web",
            status="failed",
            title_or_question="question two",
            created_at="2026-06-23T10:40:00Z",
            completed_at="2026-06-23T10:41:00Z",
            report_path=None,
            result_path="tasks/task_20260623_104000_d4e5f6/result.json",
        )
    )

    assert [task.task_id for task in store.list_finished_tasks()] == [
        "task_20260623_104000_d4e5f6",
        "task_20260623_103000_a1b2c3",
    ]

    with pytest.raises(ValueError, match="mode"):
        store.upsert_finished_task(
            TaskRecord(
                task_id="task_20260623_105000_bad000",
                mode="both",
                status="completed",
                title_or_question="bad",
                created_at="2026-06-23T10:50:00Z",
                completed_at="2026-06-23T10:51:00Z",
                report_path=None,
                result_path="tasks/task_20260623_105000_bad000/result.json",
            )
        )

    with sqlite3.connect(tmp_path / "tasks.sqlite") as connection:
        statuses = connection.execute("SELECT DISTINCT status FROM tasks").fetchall()
    assert set(status for (status,) in statuses) <= {"completed", "failed"}


def test_research_error_is_user_facing_code_and_message_only():
    error = ResearchError(code="config_missing", message="Run research-agent init first.")

    assert error.to_dict() == {"code": "config_missing", "message": "Run research-agent init first."}

    with pytest.raises(ValueError, match="unknown error code"):
        ResearchError(code="not_a_code", message="bad")


def test_core_service_exposes_v1_use_case_shells(tmp_path):
    service = CoreService(default_workspace=tmp_path)

    assert service.workspace.root == tmp_path
    for method_name in [
        "init_config",
        "run_local_research",
        "run_web_research",
        "run_both",
        "list_finished_tasks",
        "get_kb_status",
        "rebuild_kb_index",
    ]:
        assert callable(getattr(service, method_name))


def test_cli_entrypoint_has_command_skeleton():
    result = subprocess.run(
        [sys.executable, "-m", "research_agent.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "research-agent" in result.stdout
    assert "local" in result.stdout
    assert "web" in result.stdout
    assert "kb" in result.stdout
