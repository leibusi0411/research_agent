from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from research_agent.core.config import InitConfigRequest
from research_agent.core.errors import ResearchError
from research_agent.core.service import CoreService
from research_agent.core.tasks import TaskRecord


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


def add_finished_web_task(
    service: CoreService,
    workspace: Path,
    task_id: str,
    *,
    report_dir: str = "reports/web",
    report_name: str = "langgraph-notes-2026-06-24.md",
) -> Path:
    """Persist a completed Web Research task with a Web Report File on disk."""
    reports_dir = workspace / report_dir
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / report_name
    report_path.write_text(
        "\n".join(
            [
                "---",
                'title: "LangGraph Notes"',
                f'task_id: "{task_id}"',
                'created_at: "2026-06-24T10:00:00Z"',
                "---",
                "",
                "# LangGraph Notes",
                "",
                "## Summary",
                "",
                "LangGraph uses a state graph.",
                "",
                "## Findings",
                "",
                "- Nodes are roles [1]",
                "",
                "## Sources",
                "",
                "1. LangGraph docs - https://example.com/docs",
                "",
            ]
        ),
        encoding="utf-8",
    )
    service.task_store.upsert_finished_task(
        TaskRecord(
            task_id=task_id,
            mode="web",
            status="completed",
            title_or_question="LangGraph notes",
            created_at="2026-06-24T10:00:00Z",
            completed_at="2026-06-24T10:05:00Z",
            report_path=str(report_path),
            result_path=str(workspace / "tasks" / task_id / "result.json"),
        )
    )
    return report_path


def test_deposit_web_report_copies_report_into_vault(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    report_path = add_finished_web_task(service, workspace, "task_20260624_100000_bbbbbb")

    result = service.deposit_web_report("task_20260624_100000_bbbbbb")

    deposited = Path(result["vault_path"])
    assert deposited.parent == vault / "web-research"
    assert deposited.name == report_path.name
    assert deposited.read_text(encoding="utf-8") == report_path.read_text(encoding="utf-8")


def test_deposit_unknown_task_fails_with_task_not_found(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)

    with pytest.raises(ResearchError) as excinfo:
        service.deposit_web_report("task_20260624_100000_aaaaaa")

    assert excinfo.value.code == "task_not_found"


def test_deposit_local_task_fails_with_invalid_task_mode(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    service.task_store.upsert_finished_task(
        TaskRecord(
            task_id="task_20260624_100000_aaaaaa",
            mode="local",
            status="completed",
            title_or_question="local question",
            created_at="2026-06-24T10:00:00Z",
            completed_at="2026-06-24T10:00:01Z",
            report_path=None,
            result_path=str(workspace / "tasks" / "task_20260624_100000_aaaaaa" / "result.json"),
        )
    )

    with pytest.raises(ResearchError) as excinfo:
        service.deposit_web_report("task_20260624_100000_aaaaaa")

    assert excinfo.value.code == "invalid_task_mode"


def test_deposit_failed_web_task_fails_with_report_missing(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    service.task_store.upsert_finished_task(
        TaskRecord(
            task_id="task_20260624_100000_aaaaaa",
            mode="web",
            status="failed",
            title_or_question="failed web",
            created_at="2026-06-24T10:00:00Z",
            completed_at="2026-06-24T10:00:01Z",
            report_path=None,
            result_path=str(workspace / "tasks" / "task_20260624_100000_aaaaaa" / "result.json"),
        )
    )

    with pytest.raises(ResearchError) as excinfo:
        service.deposit_web_report("task_20260624_100000_aaaaaa")

    assert excinfo.value.code == "report_missing"


def test_deposit_twice_fails_with_already_deposited(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    add_finished_web_task(service, workspace, "task_20260624_100000_bbbbbb")
    service.deposit_web_report("task_20260624_100000_bbbbbb")

    with pytest.raises(ResearchError) as excinfo:
        service.deposit_web_report("task_20260624_100000_bbbbbb")

    assert excinfo.value.code == "already_deposited"


# ---------------------------------------------------------------------------
# CLI seam (subprocess, per project convention)
# ---------------------------------------------------------------------------


def run_cli(config_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["RESEARCH_AGENT_CONFIG_PATH"] = str(config_path)
    src_path = str(Path(__file__).resolve().parents[1] / "src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not existing_pythonpath else os.pathsep.join([src_path, existing_pythonpath])
    return subprocess.run(
        [sys.executable, "-m", "research_agent.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_task_deposit_cli_copies_report_into_vault(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    add_finished_web_task(service, workspace, "task_20260624_100000_bbbbbb")

    result = run_cli(config_path, "task", "deposit", "task_20260624_100000_bbbbbb")

    assert result.returncode == 0
    deposited = vault / "web-research" / "langgraph-notes-2026-06-24.md"
    assert deposited.exists()
    assert str(deposited) in result.stdout


def test_task_deposit_cli_unknown_task_exits_nonzero(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)

    result = run_cli(config_path, "task", "deposit", "task_20260624_100000_aaaaaa")

    assert result.returncode != 0
    assert "[task_not_found]" in result.stdout


# ---------------------------------------------------------------------------
# API seam
# ---------------------------------------------------------------------------


def test_task_deposit_api_copies_report_into_vault(tmp_path):
    from fastapi.testclient import TestClient

    from research_agent.api.app import create_app

    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    add_finished_web_task(service, workspace, "task_20260624_100000_bbbbbb")
    client = TestClient(create_app(config_path=config_path))

    response = client.post("/api/tasks/task_20260624_100000_bbbbbb/deposit")

    assert response.status_code == 200
    deposited = Path(response.json()["vault_path"])
    assert deposited.parent == vault / "web-research"
    assert deposited.exists()


def test_task_deposit_api_unknown_task_returns_404(tmp_path):
    from fastapi.testclient import TestClient

    from research_agent.api.app import create_app

    config_path, workspace, vault = write_config(tmp_path)
    client = TestClient(create_app(config_path=config_path))

    response = client.post("/api/tasks/task_20260624_100000_aaaaaa/deposit")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "task_not_found"


# ---------------------------------------------------------------------------
# Review follow-up coverage (R-149+)
# ---------------------------------------------------------------------------


def test_deposit_skips_non_utf8_note_in_deposit_dir(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    add_finished_web_task(service, workspace, "task_20260624_100000_bbbbbb")
    deposit_dir = vault / "web-research"
    deposit_dir.mkdir()
    (deposit_dir / "gbk-note.md").write_bytes("中文笔记".encode("gbk"))

    result = service.deposit_web_report("task_20260624_100000_bbbbbb")

    assert Path(result["vault_path"]).exists()


def test_deposit_fails_when_vault_directory_missing(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    add_finished_web_task(service, workspace, "task_20260624_100000_bbbbbb")
    vault.rmdir()

    with pytest.raises(ResearchError) as excinfo:
        service.deposit_web_report("task_20260624_100000_bbbbbb")

    assert excinfo.value.code == "config_invalid"


def test_deposit_completed_task_with_deleted_report_file_fails_with_report_missing(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    report_path = add_finished_web_task(service, workspace, "task_20260624_100000_bbbbbb")
    report_path.unlink()

    with pytest.raises(ResearchError) as excinfo:
        service.deposit_web_report("task_20260624_100000_bbbbbb")

    assert excinfo.value.code == "report_missing"


def test_deposit_uses_suffix_when_filename_collides_with_other_task(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    add_finished_web_task(service, workspace, "task_20260624_100000_bbbbbb")
    # Same report filename, different task (stored under a different source dir).
    add_finished_web_task(
        service,
        workspace,
        "task_20260624_110000_cccccc",
        report_dir="reports/web-archive",
        report_name="langgraph-notes-2026-06-24.md",
    )

    first = service.deposit_web_report("task_20260624_100000_bbbbbb")
    second = service.deposit_web_report("task_20260624_110000_cccccc")

    assert Path(first["vault_path"]).name == "langgraph-notes-2026-06-24.md"
    assert Path(second["vault_path"]).name == "langgraph-notes-2026-06-24-2.md"


def test_task_deposit_api_already_deposited_returns_409(tmp_path):
    from fastapi.testclient import TestClient

    from research_agent.api.app import create_app

    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    add_finished_web_task(service, workspace, "task_20260624_100000_bbbbbb")
    client = TestClient(create_app(config_path=config_path))
    client.post("/api/tasks/task_20260624_100000_bbbbbb/deposit")

    response = client.post("/api/tasks/task_20260624_100000_bbbbbb/deposit")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_deposited"


def test_task_deposit_cli_invalid_task_id_exits_with_config_invalid(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)

    result = run_cli(config_path, "task", "deposit", "garbage")

    assert result.returncode != 0
    assert "[config_invalid]" in result.stdout


def test_delete_unknown_task_api_returns_404_task_not_found(tmp_path):
    """Regression: R-132 introduced code=task_not_found but never registered it
    in VALID_ERROR_CODES, so this path raised ValueError instead of 404."""
    from fastapi.testclient import TestClient

    from research_agent.api.app import create_app

    config_path, workspace, vault = write_config(tmp_path)
    client = TestClient(create_app(config_path=config_path))

    response = client.delete("/api/tasks/task_20260624_100000_aaaaaa")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "task_not_found"


def test_deposit_ignores_task_id_mentioned_only_in_note_body(tmp_path):
    """Idempotency scans frontmatter only: a body mention must not block deposit."""
    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    add_finished_web_task(service, workspace, "task_20260624_100000_bbbbbb")
    deposit_dir = vault / "web-research"
    deposit_dir.mkdir()
    (deposit_dir / "other-note.md").write_text(
        '---\ntitle: "Other"\n---\n\n正文里提到 task_id: "task_20260624_100000_bbbbbb" 不算已沉淀\n',
        encoding="utf-8",
    )

    result = service.deposit_web_report("task_20260624_100000_bbbbbb")

    assert Path(result["vault_path"]).exists()


def test_deposit_unreadable_report_file_fails_with_file_write_error(tmp_path):
    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    report_path = add_finished_web_task(service, workspace, "task_20260624_100000_bbbbbb")
    report_path.write_bytes("中文报告".encode("gbk"))

    with pytest.raises(ResearchError) as excinfo:
        service.deposit_web_report("task_20260624_100000_bbbbbb")

    assert excinfo.value.code == "file_write_error"


class _FixedEmbeddingClient:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _text in texts]


def test_deposited_report_becomes_searchable_after_kb_rebuild(tmp_path, monkeypatch):
    """The closed loop: deposit → kb rebuild → Local RAG retrieves the note."""
    monkeypatch.setenv("RESEARCH_AGENT_OFFLINE", "1")
    config_path, workspace, vault = write_config(tmp_path)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    add_finished_web_task(service, workspace, "task_20260624_100000_bbbbbb")
    service.deposit_web_report("task_20260624_100000_bbbbbb")

    status = service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())

    assert "error" not in status
    assert status["file_count"] == 1
    result = service.run_local_research("state graph")
    assert result["status"] == "completed"
    source_paths = [item["source_path"] for item in result["local_results"]]
    assert any("web-research" in path for path in source_paths)


def test_deposit_triggers_incremental_index_update(tmp_path, monkeypatch):
    config_path, workspace, vault = write_config(tmp_path)
    monkeypatch.delenv("RESEARCH_AGENT_OFFLINE", raising=False)
    service = CoreService(default_workspace=workspace, config_path=config_path)
    add_finished_web_task(service, workspace, "task_20260624_100000_bbbbbb")

    calls: list[dict] = []

    def fake_update(self, *, max_files=None, embedding_client=None):
        calls.append({"max_files": max_files})
        return {"status": "ready", "updated_files": 1, "skipped": False}

    monkeypatch.setattr(CoreService, "update_kb_index", fake_update)

    result = service.deposit_web_report("task_20260624_100000_bbbbbb")

    # Deposit is the deterministic trigger for refreshing the index (ADR-0048):
    # the deposited file is the only certain change, so the incremental update
    # processes just a handful of files.
    assert calls and calls[0]["max_files"] == 5
    assert result["index_update"]["status"] == "ready"


def test_deposit_skips_index_update_in_offline_mode(tmp_path, monkeypatch):
    config_path, workspace, vault = write_config(tmp_path)
    monkeypatch.setenv("RESEARCH_AGENT_OFFLINE", "1")
    service = CoreService(default_workspace=workspace, config_path=config_path)
    add_finished_web_task(service, workspace, "task_20260624_100000_bbbbbb")

    def fail_update(self, **_kwargs):
        raise AssertionError("offline mode must not update the index")

    monkeypatch.setattr(CoreService, "update_kb_index", fail_update)

    result = service.deposit_web_report("task_20260624_100000_bbbbbb")

    assert "index_update" not in result
    assert result["vault_path"]
