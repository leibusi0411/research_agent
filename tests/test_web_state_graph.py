import json
from pathlib import Path
from unittest.mock import MagicMock

from research_agent.core.config import InitConfigRequest
from research_agent.core.ids import utc_now_iso
from research_agent.core.providers import FakeChatModelClient
from research_agent.core.service import CoreService
from research_agent.web.schemas import (
    ExecutorOutput,
    Finding,
    PlannerOutput,
    PlannerSubtaskDraft,
    SupervisorOutput,
    WebResearchState,
    WebSource,
)
from research_agent.web.state_graph import ResearchExecutor, StateGraphRunner


def configured_service(tmp_path: Path) -> tuple[CoreService, Path, Path]:
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
    return service, config_path, workspace


def _make_planner_response(title: str, questions: list[str]) -> str:
    return json.dumps({
        "research_title": title,
        "subtasks": [{"question": q} for q in questions],
    })


def _make_supervisor_response(route: str, reason: str = "Reason", **kwargs) -> str:
    return json.dumps({
        "route": route,
        "reason": reason,
        "next_subtask_ids": kwargs.get("next_subtask_ids", []),
        "skip_subtask_ids": kwargs.get("skip_subtask_ids", []),
        "plan_revision_request": kwargs.get("plan_revision_request"),
        "research_gaps": kwargs.get("research_gaps", []),
        "saturation": kwargs.get("saturation", False),
    })


def _make_executor_response(subtask_id: str, finding_text: str, source_url: str) -> str:
    return json.dumps({
        "subtask_id": subtask_id,
        "status": "completed",
        "findings": [{
            "finding_id": f"f_{subtask_id}",
            "subtask_id": subtask_id,
            "text": finding_text,
            "source_ids": [f"src_{subtask_id}"],
        }],
        "sources": [{
            "source_id": f"src_{subtask_id}",
            "title": f"Source for {subtask_id}",
            "url": source_url,
            "fetched_at": utc_now_iso(),
        }],
        "failure_reason": None,
    })


def _make_tool_plan_response(query: str = "test query") -> str:
    return json.dumps({
        "tool_calls": [
            {"name": "web.search", "arguments": {"query": query, "max_results": 5}},
        ],
    })


def _make_curator_response(title: str, summary: str) -> str:
    return json.dumps({
        "title": title,
        "summary": summary,
        "findings": [],
        "sources": [],
    })


def test_research_executor_executes_single_subtask(tmp_path):
    """ResearchExecutor should execute a single subtask and return ExecutorOutput."""
    mock_gateway = MagicMock()
    mock_gateway.call.return_value = MagicMock(
        status="ok",
        data={"results": [{"title": "Test", "url": "https://example.com", "content": "Test content"}]},
    )

    executor = ResearchExecutor(tool_gateway=mock_gateway, max_concurrent_subtasks=1)
    state = WebResearchState(original_question="What is LangGraph?")
    state.add_planner_output(PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))

    # Mock the LLM to return tool plan then synthesis response
    mock_chat = FakeChatModelClient([
        _make_tool_plan_response("LangGraph architecture"),
        _make_executor_response("st_1", "LangGraph uses state graphs.", "https://example.com/arch"),
    ])

    outputs = executor.execute(state, ["st_1"], chat_model=mock_chat)

    assert len(outputs) == 1
    assert outputs[0].subtask_id == "st_1"
    assert outputs[0].status == "completed"
    assert len(outputs[0].findings) == 1
    assert "state graphs" in outputs[0].findings[0].text


def test_research_executor_executes_multiple_subtasks_concurrently(tmp_path):
    """ResearchExecutor should execute multiple subtasks."""
    mock_gateway = MagicMock()
    mock_gateway.call.return_value = MagicMock(
        status="ok",
        data={"results": [{"title": "Test", "url": "https://example.com", "content": "Test content"}]},
    )

    executor = ResearchExecutor(tool_gateway=mock_gateway, max_concurrent_subtasks=3)
    state = WebResearchState(original_question="What is LangGraph?")
    state.add_planner_output(PlannerOutput("LangGraph Research", [
        PlannerSubtaskDraft("Find architecture overview."),
        PlannerSubtaskDraft("Find usage examples."),
    ]))

    # Each subtask needs 2 LLM calls: tool plan + synthesis
    mock_chat = FakeChatModelClient([
        _make_tool_plan_response("LangGraph architecture"),
        _make_executor_response("st_1", "LangGraph uses state graphs.", "https://example.com/arch"),
        _make_tool_plan_response("LangGraph examples"),
        _make_executor_response("st_2", "LangGraph example code.", "https://example.com/example"),
    ])

    outputs = executor.execute(state, ["st_1", "st_2"], chat_model=mock_chat)

    assert len(outputs) == 2
    assert all(o.status == "completed" for o in outputs)


def test_state_graph_runner_executes_full_flow(tmp_path):
    """StateGraphRunner should orchestrate the full Plan -> Execute -> Supervise -> Curate flow."""
    _service, _config_path, workspace = configured_service(tmp_path)

    mock_gateway = MagicMock()
    mock_gateway.call.return_value = MagicMock(
        status="ok",
        data={"results": [{"title": "Test", "url": "https://example.com", "content": "Test content"}]},
    )

    chat_completions = [
        _make_planner_response("LangGraph Research", ["What is LangGraph?", "How to use LangGraph?"]),
        # Each subtask needs 2 LLM calls: tool plan + synthesis
        _make_tool_plan_response("What is LangGraph"),
        _make_executor_response("st_1", "LangGraph is a state graph framework.", "https://example.com/1"),
        _make_tool_plan_response("How to use LangGraph"),
        _make_executor_response("st_2", "LangGraph example code.", "https://example.com/2"),
        _make_supervisor_response("curate", "Enough evidence gathered.", saturation=True),
        _make_curator_response("LangGraph Research", "LangGraph is a framework for building state graphs."),
    ]

    mock_chat = FakeChatModelClient(chat_completions)

    runner = StateGraphRunner(
        workspace=str(workspace),
        chat_model=mock_chat,
        tool_gateway=mock_gateway,
        max_retrieval_rounds=3,
        max_concurrent_subtasks=3,
    )

    result = runner.run("What is LangGraph?")

    assert result["status"] == "completed"
    assert result["curator_output"]["title"] == "LangGraph Research"
    assert "report_path" in result