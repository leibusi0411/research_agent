import json
from pathlib import Path
from unittest.mock import MagicMock

from research_agent.core.config import InitConfigRequest
from research_agent.core.ids import utc_now_iso
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


class _SequencedChatClient:
    def __init__(self, completions: list[str]) -> None:
        self._completions = list(completions)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        self.prompts.append(prompt)
        return self._completions.pop(0) if self._completions else ""


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


def _make_empty_tool_plan_response() -> str:
    return json.dumps({"tool_calls": []})


def _make_curator_response(title: str, summary: str) -> str:
    return json.dumps({
        "title": title,
        "summary": summary,
        "findings": [],
        "sources": [],
    })


def _make_chat_models(client: object) -> dict[str, object]:
    """Build per-role chat_models dict, all sharing the same client."""
    return {"planner": client, "executor": client, "supervisor": client, "curator": client}


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
    mock_chat = _SequencedChatClient([
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
    mock_chat = _SequencedChatClient([
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

    mock_chat = _SequencedChatClient(chat_completions)

    runner = StateGraphRunner(
        workspace=str(workspace),
        chat_models=_make_chat_models(mock_chat),
        tool_gateway=mock_gateway,
        max_retrieval_rounds=3,
        max_concurrent_subtasks=1,  # single-threaded: _SequencedChatClient is not thread-safe
    )

    result = runner.run("What is LangGraph?")

    assert result["status"] == "completed"
    assert result["curator_output"]["title"] == "LangGraph Research"
    assert "report_path" in result


def test_research_executor_empty_tool_calls_returns_failed(tmp_path):
    """When LLM returns empty tool_calls, executor should return failed without synthesis."""
    mock_gateway = MagicMock()
    mock_gateway.call.return_value = MagicMock(
        status="ok",
        data={"results": []},
    )

    executor = ResearchExecutor(tool_gateway=mock_gateway, max_concurrent_subtasks=1)
    state = WebResearchState(original_question="What is LangGraph?")
    state.add_planner_output(PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))

    # Only one LLM response needed: empty tool plan. Synthesis should NOT be called.
    mock_chat = _SequencedChatClient([
        _make_empty_tool_plan_response(),
    ])

    outputs = executor.execute(state, ["st_1"], chat_model=mock_chat)

    assert len(outputs) == 1
    assert outputs[0].subtask_id == "st_1"
    assert outputs[0].status == "failed", f"expected status='failed' but got '{outputs[0].status}'"
    assert outputs[0].failure_reason is not None, "expected failure_reason for empty tool_calls"
    assert "no tool calls" in (outputs[0].failure_reason or "").lower(), f"failure_reason should mention empty tool calls, got: {outputs[0].failure_reason}"
    assert len(outputs[0].findings) == 0
    assert len(outputs[0].sources) == 0


def test_guard_route_redirects_revise_plan_at_max_rounds(tmp_path):
    """_guard_route should redirect revise_plan when retrieval_round >= max, not just continue_execution."""
    _service, _config_path, workspace = configured_service(tmp_path)

    mock_gateway = MagicMock()
    runner = StateGraphRunner(
        workspace=str(workspace),
        chat_models=_make_chat_models(_SequencedChatClient([])),
        tool_gateway=mock_gateway,
        max_retrieval_rounds=2,
        max_concurrent_subtasks=3,
    )

    state = WebResearchState(original_question="test")
    state.findings = [Finding(finding_id="f_1", subtask_id="st_1", text="Found something.", source_ids=["src_1"])]
    state.sources = [WebSource(source_id="src_1", title="Source 1", url="https://example.com", fetched_at=utc_now_iso())]
    state.retrieval_round = 3  # >= max_retrieval_rounds

    # Currently: revise_plan is NOT guarded → returns "revise_plan" unchanged (BUG)
    # After fix: revise_plan should be redirected to "curate" (findings exist)
    result = runner._guard_route(state, "revise_plan")
    assert result == "curate", f"expected revise_plan→curate at max rounds, got: {result}"

    # When no findings, should redirect to "fail"
    state_no_findings = WebResearchState(original_question="test")
    state_no_findings.retrieval_round = 3
    result2 = runner._guard_route(state_no_findings, "revise_plan")
    assert result2 == "fail", f"expected revise_plan→fail when no findings, got: {result2}"


def test_guard_route_preserves_curate_and_fail_at_any_round(tmp_path):
    """_guard_route should pass through 'curate' and 'fail' unchanged regardless of round."""
    _service, _config_path, workspace = configured_service(tmp_path)

    runner = StateGraphRunner(
        workspace=str(workspace),
        chat_models=_make_chat_models(_SequencedChatClient([])),
        tool_gateway=MagicMock(),
        max_retrieval_rounds=2,
        max_concurrent_subtasks=3,
    )

    state = WebResearchState(original_question="test")
    state.retrieval_round = 3  # >= max

    # curate and fail should always pass through unchanged
    assert runner._guard_route(state, "curate") == "curate"
    assert runner._guard_route(state, "fail") == "fail"


def test_continue_execution_with_empty_next_subtask_ids_in_loop(tmp_path):
    """When supervisor returns continue_execution with no next_subtask_ids,
    the loop should redirect to termination rather than continue with nothing."""
    _service, _config_path, workspace = configured_service(tmp_path)

    mock_gateway = MagicMock()
    mock_gateway.call.return_value = MagicMock(
        status="ok",
        data={"results": [{"title": "Test", "url": "https://example.com", "content": "Test content"}]},
    )

    # Two subtasks, both get executed, supervisor says continue with empty list
    # System should curate since findings exist
    chat_completions = [
        _make_planner_response("Test", ["Q1.", "Q2."]),
        _make_tool_plan_response("Q1"),
        _make_executor_response("st_1", "Finding 1.", "https://example.com/1"),
        _make_tool_plan_response("Q2"),
        _make_executor_response("st_2", "Finding 2.", "https://example.com/2"),
        # Supervisor: continue_execution + empty next_subtask_ids + skip remaining
        _make_supervisor_response("continue_execution", "Done.", next_subtask_ids=[], skip_subtask_ids=[]),
        _make_curator_response("Test", "All done."),
    ]

    mock_chat = _SequencedChatClient(chat_completions)

    runner = StateGraphRunner(
        workspace=str(workspace),
        chat_models=_make_chat_models(mock_chat),
        tool_gateway=mock_gateway,
        max_retrieval_rounds=3,
        max_concurrent_subtasks=3,
    )

    result = runner.run("test question")

    # Should complete: empty next_subtask_ids → redirect to curate (findings exist)
    assert result["status"] == "completed", f"got {result.get('status')}: {result.get('error', {})}"