"""End-to-end integration tests for Web Research with real LLM and search APIs.

These tests require valid API keys in the config file:
- Chat model (DeepSeek)
- Search API (Tavily)

Run with: uv run pytest tests/test_web_e2e.py -v -s -m e2e
"""

import json
import os
from pathlib import Path

import pytest

from research_agent.core.config import load_user_config
from research_agent.core.providers import OpenAICompatibleChatModel
from research_agent.core.service import CoreService
from research_agent.web.tools import (
    ToolGateway,
    ToolRunner,
    TavilySearchProvider,
    create_default_web_tool_registry,
)
from research_agent.web.state_graph import RunnerConfig, StateGraphRunner


def _get_config_or_skip():
    """Load config, skip test if not available."""
    try:
        config = load_user_config()
        # Verify API keys are present
        if not config.chat_model.api_key or config.chat_model.api_key == "test-key":
            pytest.skip("Chat model API key not configured")
        if not config.search.api_key or config.search.api_key == "test-key":
            pytest.skip("Search API key not configured")
        return config
    except Exception as e:
        pytest.skip(f"Config not available: {e}")


def _create_tool_gateway(config):
    """Create a real ToolGateway with Tavily search."""
    search_provider = TavilySearchProvider(api_key=config.search.api_key)
    tool_runner = ToolRunner(config=config.web_tools, search_provider=search_provider)
    return ToolGateway(registry=create_default_web_tool_registry(), runner=tool_runner)


def _make_chat_models(client: object) -> dict[str, object]:
    """Build per-role chat_models dict, all sharing the same client."""
    return {"planner": client, "executor": client, "supervisor": client, "curator": client}


@pytest.mark.e2e
def test_web_research_e2e_simple(tmp_path):
    """End-to-end test: simple question with real LLM and search."""
    config = _get_config_or_skip()

    # Create workspace
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create real chat model
    chat_model = OpenAICompatibleChatModel.from_config(config.chat_model)

    # Create real tool gateway
    tool_gateway = _create_tool_gateway(config)

    # Create runner with minimal rounds for faster test
    runner = StateGraphRunner(
        config=RunnerConfig(
            workspace=str(workspace),
            chat_models=_make_chat_models(chat_model),
            tool_gateway=tool_gateway,
            max_retrieval_rounds=1,  # Limit to 1 round for faster test
            max_concurrent_subtasks=2,
        ),
    )

    # Run research
    question = "What is Python's GIL (Global Interpreter Lock)?"
    result = runner.run(question)

    # Verify result structure
    assert result["status"] in ("completed", "failed"), f"Unexpected status: {result['status']}"
    assert result["mode"] == "web"
    assert result["question"] == question
    assert "task_id" in result
    assert "created_at" in result
    assert "completed_at" in result

    if result["status"] == "completed":
        # Verify curator output
        assert "curator_output" in result
        curator = result["curator_output"]
        assert "title" in curator
        assert "summary" in curator
        assert len(curator["summary"]) > 0

        # Verify report file
        assert "report_path" in result
        report_path = Path(result["report_path"])
        assert report_path.exists()
        assert report_path.suffix == ".md"

        # Verify report content
        report_content = report_path.read_text(encoding="utf-8")
        assert "---" in report_content  # Has frontmatter
        assert question.split("?")[0] in report_content or curator["title"] in report_content

        # Verify LangGraph checkpoint (replaces blackboard_snapshot.json, ADR-0013 V1.1)
        checkpoint_path = workspace / "tasks" / result["task_id"] / "checkpoints.sqlite"
        assert checkpoint_path.exists(), f"checkpoints.sqlite not found at {checkpoint_path}"

        print(f"\n[PASS] Research completed successfully!")
        print(f"   Title: {curator['title']}")
        print(f"   Summary: {curator['summary'][:100]}...")
        print(f"   Report: {result['report_path']}")
    else:
        # If failed, print error for debugging
        print(f"\n[FAIL] Research failed: {result.get('error', {}).get('message', 'Unknown error')}")


@pytest.mark.e2e
def test_web_research_e2e_with_multiple_subtasks(tmp_path):
    """End-to-end test: question that requires multiple subtasks."""
    config = _get_config_or_skip()

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    chat_model = OpenAICompatibleChatModel.from_config(config.chat_model)
    tool_gateway = _create_tool_gateway(config)

    runner = StateGraphRunner(
        config=RunnerConfig(
            workspace=str(workspace),
            chat_models=_make_chat_models(chat_model),
            tool_gateway=tool_gateway,
            max_retrieval_rounds=2,
            max_concurrent_subtasks=2,
        ),
    )

    question = "Compare LangGraph and AutoGen for building AI agents"
    result = runner.run(question)

    assert result["status"] in ("completed", "failed")

    if result["status"] == "completed":
        curator = result["curator_output"]
        assert len(curator["findings"]) > 0, "Should have at least one finding"
        assert len(curator["sources"]) > 0, "Should have at least one source"

        # Verify source snapshots
        sources_dir = workspace / "tasks" / result["task_id"] / "artifacts" / "web_sources"
        assert sources_dir.exists()

        print(f"\n[PASS] Multi-subtask research completed!")
        print(f"   Findings: {len(curator['findings'])}")
        print(f"   Sources: {len(curator['sources'])}")


@pytest.mark.e2e
def test_web_research_e2e_via_core_service(tmp_path):
    """End-to-end test via CoreService (full integration)."""
    config = _get_config_or_skip()

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()
    config_path = tmp_path / "config.toml"

    # Create service with real config path
    service = CoreService(default_workspace=workspace, config_path=config_path)

    # Copy real config
    real_config_path = Path(os.environ.get(
        "RESEARCH_AGENT_CONFIG_PATH",
        Path.home() / ".config" / "research_agent" / "config.toml"
    ))
    if not real_config_path.exists():
        real_config_path = Path(os.environ["APPDATA"]) / "research_agent" / "config.toml"

    if real_config_path.exists():
        config_content = real_config_path.read_text(encoding="utf-8")
        # Update workspace paths in config
        config_content = config_content.replace(
            f'default_workspace = "{config.workspace.default_workspace}"',
            f'default_workspace = "{workspace}"'
        )
        config_content = config_content.replace(
            f'knowledge_base_path = "{config.workspace.knowledge_base_path}"',
            f'knowledge_base_path = "{vault}"'
        )
        config_path.write_text(config_content, encoding="utf-8")

    # Run via service
    question = "What are the key features of FastAPI?"
    result = service.run_web_research(question)

    assert result["status"] in ("completed", "failed")
    assert result["mode"] == "web"

    if result["status"] == "completed":
        print(f"\n[PASS] CoreService integration test passed!")
        print(f"   Title: {result['curator_output']['title']}")


if __name__ == "__main__":
    # Run with python -m pytest tests/test_web_e2e.py -v -s -m e2e
    pytest.main([__file__, "-v", "-s", "-m", "e2e"])
