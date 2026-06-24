from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from research_agent.api.app import create_app
from research_agent.core.config import InitConfigRequest
from research_agent.core.service import CoreService
from research_agent.web.fake_runtime import FakeWebResearchRuntime
from tests.fakes import FixedEmbeddingClient


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
    service.rebuild_kb_index(embedding_client=FixedEmbeddingClient())
    app = create_app(
        config_path=config_path,
        web_runtime_factory=lambda workspace_path: FakeWebResearchRuntime(workspace=workspace_path, event_delay_seconds=0.05),
        embedding_client_factory=lambda _config: FixedEmbeddingClient(),
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
    rebuild = configured.post("/api/kb/rebuild")
    status = configured.get("/api/kb/status")

    assert rebuild.status_code == 200
    assert rebuild.json()["status"] == "ready"
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
