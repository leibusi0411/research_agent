import os
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from research_agent.core.config import InitConfigRequest
from research_agent.core.service import CoreService


def configured_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
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
    env = os.environ.copy()
    env["RESEARCH_AGENT_CONFIG_PATH"] = str(config_path)
    src_path = str(Path(__file__).resolve().parents[1] / "src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not existing_pythonpath else os.pathsep.join([src_path, existing_pythonpath])
    env["RESEARCH_AGENT_FAKE_WEB"] = "1"  # CLI subprocess must use fake runtime for offline tests
    return env, workspace


def run_web(env: dict[str, str], question: str = "LangGraph architecture") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "research_agent.cli", "web", question],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_web_cli_success_streams_progress_and_prints_report(tmp_path):
    env, workspace = configured_env(tmp_path)

    result = run_web(env)

    assert result.returncode == 0
    assert "web_planning" in result.stdout
    assert "web_execution" in result.stdout
    assert "web_supervision" in result.stdout
    assert "web_curation" in result.stdout
    assert "Summary" in result.stdout
    assert "Findings" in result.stdout
    assert "Sources" in result.stdout
    assert "report_path:" in result.stdout
    reports = list((workspace / "reports" / "web").glob("*.md"))
    assert reports
    task_rows = finished_task_rows(workspace)
    assert len(task_rows) == 1
    task_id, mode, status, report_path, result_path = task_rows[0]
    assert mode == "web"
    assert status == "completed"
    assert Path(report_path).exists()
    assert Path(result_path).exists()
    task_result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    assert task_result["task_id"] == task_id
    assert task_result["status"] == "completed"


def test_web_cli_phase_output_is_available_before_process_exit(tmp_path):
    env, _workspace = configured_env(tmp_path)
    env["RESEARCH_AGENT_FAKE_WEB_EVENT_DELAY_SECONDS"] = "0.2"
    process = subprocess.Popen(
        [sys.executable, "-m", "research_agent.cli", "web", "LangGraph streaming"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        first_line = process.stdout.readline() if process.stdout is not None else ""
        assert "web_planning" in first_line
        assert process.poll() is None
    finally:
        stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 0, stdout + stderr


def test_web_cli_runtime_failure_is_nonzero(tmp_path):
    env, workspace = configured_env(tmp_path)
    env["RESEARCH_AGENT_FAKE_WEB_PRODUCE_FINDINGS"] = "0"
    env["RESEARCH_AGENT_FAKE_WEB_MAX_ROUNDS"] = "0"

    result = run_web(env, "No findings")

    assert result.returncode == 1
    assert "[runtime_error]" in result.stdout
    rows = finished_task_rows(workspace)
    assert len(rows) == 1
    assert rows[0][2] == "failed"
    assert rows[0][3] is None
    assert json.loads(Path(rows[0][4]).read_text(encoding="utf-8"))["status"] == "failed"


def test_web_cli_schema_validation_failure_is_nonzero(tmp_path):
    env, workspace = configured_env(tmp_path)
    env["RESEARCH_AGENT_FAKE_WEB_SCHEMA_FAILURE"] = "1"

    result = run_web(env, "Bad schema")

    assert result.returncode == 1
    assert "[schema_validation_failed]" in result.stdout
    rows = finished_task_rows(workspace)
    assert len(rows) == 1
    assert rows[0][2] == "failed"
    assert json.loads(Path(rows[0][4]).read_text(encoding="utf-8"))["status"] == "failed"


def test_web_cli_report_write_failure_is_nonzero(tmp_path):
    env, workspace = configured_env(tmp_path)
    env["RESEARCH_AGENT_FAKE_WEB_REPORT_FAILURE"] = "1"

    result = run_web(env, "Report failure")

    assert result.returncode == 1
    assert "[file_write_error]" in result.stdout
    rows = finished_task_rows(workspace)
    assert len(rows) == 1
    assert rows[0][2] == "failed"
    assert rows[0][3] is None
    assert json.loads(Path(rows[0][4]).read_text(encoding="utf-8"))["status"] == "failed"


def finished_task_rows(workspace: Path) -> list[tuple[str, str, str, str | None, str]]:
    with sqlite3.connect(workspace / "tasks.sqlite") as connection:
        return connection.execute(
            "SELECT task_id, mode, status, report_path, result_path FROM tasks ORDER BY created_at DESC"
        ).fetchall()
