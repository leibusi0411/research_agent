from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from research_agent.core.config import InitConfigRequest
from research_agent.core.service import CoreService
from research_agent.core.tasks import TaskRecord


class _FixedEmbeddingClient:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _text in texts]


def configured_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
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
    env = os.environ.copy()
    env["RESEARCH_AGENT_CONFIG_PATH"] = str(config_path)
    src_path = str(Path(__file__).resolve().parents[1] / "src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not existing_pythonpath else os.pathsep.join([src_path, existing_pythonpath])
    return env, workspace


def run_cli(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "research_agent.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_task_list_displays_finished_tasks_sorted_by_created_at_desc(tmp_path):
    env, workspace = configured_env(tmp_path)
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
