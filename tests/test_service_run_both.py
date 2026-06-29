"""Tests for CoreService.run_both error handling."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from research_agent.core.config import InitConfigRequest
from research_agent.core.service import CoreService


class _FixedEmbeddingClient:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _text in texts]


def _configured_service(tmp_path: Path) -> CoreService:
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
    service.rebuild_kb_index(embedding_client=_FixedEmbeddingClient())
    return service


def test_run_both_survives_unexpected_exception_from_family(tmp_path):
    """If _run_family_result raises a non-ResearchError, run_both should
    return a failed result instead of crashing."""
    service = _configured_service(tmp_path)

    original = CoreService._run_family_result

    def patched_run_family_result(self, family, question, web_runtime):
        if family == "local":
            raise TypeError("simulated unexpected error")
        return original(self, family, question, web_runtime)

    with patch.object(CoreService, "_run_family_result", patched_run_family_result):
        mock_runtime = MagicMock()
        mock_runtime.run.return_value = {
            "task_id": "task_test_web", "mode": "web", "question": "test question",
            "status": "completed", "created_at": "2026-06-28T00:00:00Z",
            "completed_at": "2026-06-28T00:00:01Z",
            "curator_output": {"title": "Test", "summary": "Summary", "findings": [], "sources": []},
            "report_path": "/tmp/report.md",
        }
        result = service.run_both("test question", web_runtime=mock_runtime)

    assert result["status"] == "failed"
    assert result["local"]["status"] == "failed"
    assert "error" in result["local"]
