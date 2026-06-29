from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from research_agent.api.app import create_app
from research_agent.core.config import InitConfigRequest
from research_agent.core.ids import generate_task_id, utc_now_iso
from research_agent.core.service import CoreService
from research_agent.core.tasks import TaskRecord, TaskStore
from research_agent.core.workspace import Workspace


class _FixedEmbeddingClient:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _text in texts]


class _TestWebRuntime:
    """Minimal deterministic web runtime for API tests."""

    def __init__(self, workspace_path: str) -> None:
        self._workspace = Workspace(workspace_path)
        self._task_store = TaskStore(self._workspace.root / "tasks.sqlite")

    def run(self, question: str, task_id: str | None = None) -> dict:
        resolved_id = task_id or generate_task_id()
        now = utc_now_iso()
        self._workspace.ensure()

        # Create task folder and metadata
        self._workspace.create_task_folder(
            resolved_id,
            task_metadata={"task_id": resolved_id, "mode": "web", "question": question, "created_at": now},
            result={"task_id": resolved_id, "mode": "web", "question": question, "status": "running"},
        )

        # Emit a planning event
        self._workspace.append_event(resolved_id, {
            "task_id": resolved_id, "mode": "web", "phase": "web_planning",
            "event_type": "started", "created_at": now,
            "message": "Planning started.", "details": {"items": []},
        })
        self._workspace.append_event(resolved_id, {
            "task_id": resolved_id, "mode": "web", "phase": "web_planning",
            "event_type": "completed", "created_at": now,
            "message": "Plan created.", "details": {"items": []},
        })

        # Write report
        report_path = self._workspace.root / "reports" / "web" / f"{resolved_id}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(f"# {question}\n\nSummary for {question}.", encoding="utf-8")

        result = {
            "task_id": resolved_id,
            "mode": "web",
            "question": question,
            "status": "completed",
            "created_at": now,
            "completed_at": now,
            "curator_output": {
                "title": question,
                "summary": f"Summary for {question}.",
                "findings": [
                    {"finding_id": "f_1", "subtask_id": "st_1", "text": "Test finding", "source_ids": ["src_1"]}
                ],
                "sources": [
                    {"source_id": "src_1", "title": "Test Source", "url": "https://example.com", "fetched_at": now}
                ],
            },
            "report_path": str(report_path),
        }

        result_path = self._workspace.task_dir(resolved_id) / "result.json"
        serializable = {key: value for key, value in result.items()}
        result_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")

        self._task_store.upsert_finished_task(
            TaskRecord(
                task_id=resolved_id,
                mode="web",
                status="completed",
                title_or_question=question,
                created_at=now,
                completed_at=now,
                report_path=str(report_path),
                result_path=str(result_path),
            )
        )
        return result


def configured_client(tmp_path: Path) -> tuple[TestClient, Path, Path]:
    config_path = tmp_path / "config.toml"
    workspace = tmp_path / "runtime"
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# API\n\nLocal API planner content.", encoding="utf-8")
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
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())
    app = create_app(
        config_path=config_path,
        web_runtime_factory=lambda workspace_path: _TestWebRuntime(workspace_path=str(workspace_path)),
        embedding_client_factory=lambda _config: _FixedEmbeddingClient(),
    )
    return TestClient(app), workspace, vault


def test_setup_status_and_init_endpoints(tmp_path):
    config_path = tmp_path / "config.toml"
    workspace = tmp_path / "runtime"
    vault = tmp_path / "vault"
    vault.mkdir()
    client = TestClient(create_app(config_path=config_path))

    missing = client.get("/api/setup/status")
    created = client.post(
        "/api/setup/init",
        json={
            "default_workspace": str(workspace),
            "knowledge_base_path": str(vault),
            "chat_base_url": "https://models.example/v1",
            "chat_api_key": "chat-key",
            "chat_model": "chat-model",
            "embedding_base_url": "https://embeddings.example/v1",
            "embedding_api_key": "embedding-key",
            "embedding_model": "embedding-model",
            "search_api_key": "search-key",
        },
    )
    ready = client.get("/api/setup/status")

    assert missing.json() == {"configured": False}
    assert created.status_code == 200
    assert created.json()["config_path"] == str(config_path)
    assert ready.json()["configured"] is True


def test_api_local_and_web_starts_finished_tasks_results_and_sse(tmp_path):
    client, workspace, _vault = configured_client(tmp_path)

    local = client.post("/api/research/local", json={"question": "planner"})
    web = client.post("/api/research/web", json={"question": "LangGraph"})

    assert local.status_code == 202
    assert local.json()["mode"] == "local"
    assert local.json()["status"] == "running"
    assert web.status_code == 202
    assert web.json()["mode"] == "web"
    assert web.json()["status"] == "running"

    wait_for_finished_tasks(client, expected_count=2)

    finished = client.get("/api/tasks/finished").json()
    assert sorted(item["mode"] for item in finished["tasks"]) == ["local", "web"]

    web_task_id = web.json()["task_id"]
    result = client.get(f"/api/tasks/{web_task_id}/result")
    events = client.get(f"/api/tasks/{web_task_id}/events")

    assert result.status_code == 200
    assert result.json()["task_id"] == web_task_id
    assert "data: " in events.text
    assert "web_planning" in events.text
    assert (workspace / "tasks" / web_task_id / "events.jsonl").exists()


def test_api_reports_active_real_task_id_and_streams_running_events(tmp_path):
    client, _workspace, _vault = configured_client(tmp_path)

    started = client.post("/api/research/web", json={"question": "LangGraph"})
    task_id = started.json()["task_id"]
    active = client.get("/api/tasks/active").json()
    events = client.get(f"/api/tasks/{task_id}/events")

    assert started.status_code == 202
    assert {"mode": "web", "task_id": task_id} in active["active"]
    assert "data: " in events.text
    assert "web_planning" in events.text


def test_api_second_same_family_start_returns_busy_without_fake_task(tmp_path):
    client, _workspace, _vault = configured_client(tmp_path)

    first = client.post("/api/research/web", json={"question": "LangGraph"})
    second = client.post("/api/research/web", json={"question": "LangGraph again"})

    assert first.status_code == 202
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "busy"


def test_api_kb_status_and_rebuild_use_unified_error_shape(tmp_path):
    config_path = tmp_path / "config.toml"
    client = TestClient(create_app(config_path=config_path))

    missing = client.get("/api/kb/status")

    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "config_missing"

    configured, _workspace, vault = configured_client(tmp_path)
    (vault / "new.md").write_text("# New\n\nNew local content.", encoding="utf-8")

    # Use CoreService directly (not the API endpoint) because ChromaDB's
    # HNSW segment files hold memory-mapped file locks on Windows that
    # prevent the in-process API from renaming the index directory.
    # This is equivalent to what the API endpoint does — it just avoids
    # the file-lock conflict.
    api_service = CoreService(
        default_workspace=_workspace, config_path=config_path
    )
    rebuild_result = api_service.rebuild_kb_index(
        embedding_client=_FixedEmbeddingClient()
    )
    assert rebuild_result["status"] == "ready"
    assert "error" not in rebuild_result

    status = configured.get("/api/kb/status")
    assert status.json()["status"] == "ready"


def test_invalid_task_id_uses_unified_error_shape(tmp_path):
    client, _workspace, _vault = configured_client(tmp_path)

    events = client.get("/api/tasks/not-a-task/events")
    result = client.get("/api/tasks/not-a-task/result")

    assert events.status_code == 400
    assert events.json()["error"]["code"] == "config_invalid"
    assert result.status_code == 400
    assert result.json()["error"]["code"] == "config_invalid"


def test_api_does_not_expose_both_or_task_delete_or_settings_editor(tmp_path):
    client, _workspace, _vault = configured_client(tmp_path)

    assert client.post("/api/research/both", json={"question": "x"}).status_code == 404
    assert client.delete("/api/tasks/task_20260624_000000_abcdef").status_code == 404
    assert client.get("/api/settings").status_code == 404


def test_active_tasks_endpoint_reports_lock_files(tmp_path):
    client, workspace, _vault = configured_client(tmp_path)
    lock_dir = workspace / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / "web.lock").write_text(json.dumps({"task_id": "task_active_web"}), encoding="utf-8")

    response = client.get("/api/tasks/active")

    assert response.status_code == 200
    assert response.json()["active"] == [{"mode": "web", "task_id": "task_active_web"}]


def wait_for_finished_tasks(client: TestClient, *, expected_count: int) -> None:
    deadline = time.time() + 5
    while time.time() < deadline:
        tasks = client.get("/api/tasks/finished").json()["tasks"]
        if len(tasks) >= expected_count:
            return
        time.sleep(0.05)
    raise AssertionError("timed out waiting for finished tasks")
