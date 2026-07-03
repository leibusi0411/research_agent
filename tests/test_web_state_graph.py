import json
import queue
import threading
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
    ResearchSubtask,
    SupervisorOutput,
    WebResearchStateDict,
    WebSource,
    _merge_subtasks,
    create_initial_state,
)
from research_agent.web.executor import ResearchExecutor
from research_agent.web.graph import route_after_supervise
from research_agent.web.state_graph import RunnerConfig, StateGraphRunner


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
    state = create_initial_state(original_question="What is LangGraph?")
    state["research_title"] = "LangGraph Research"
    state["subtasks"] = [ResearchSubtask(subtask_id="st_1", question="Find architecture overview.")]

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
    state = create_initial_state(original_question="What is LangGraph?")
    state["research_title"] = "LangGraph Research"
    state["subtasks"] = [
        ResearchSubtask(subtask_id="st_1", question="Find architecture overview."),
        ResearchSubtask(subtask_id="st_2", question="Find usage examples."),
    ]

    # R-120: Use _ThreadSafeChatClient instead of _SequencedChatClient
    # to avoid non-deterministic pop ordering under concurrent execution.
    completions = [
        _make_tool_plan_response("LangGraph architecture"),
        _make_executor_response("st_1", "LangGraph uses state graphs.", "https://example.com/arch"),
        _make_tool_plan_response("LangGraph examples"),
        _make_executor_response("st_2", "LangGraph example code.", "https://example.com/example"),
    ]
    mock_chat = _ThreadSafeChatClient(completions)

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
        config=RunnerConfig(
            workspace=str(workspace),
            chat_models=_make_chat_models(mock_chat),
            tool_gateway=mock_gateway,
            max_retrieval_rounds=3,
            max_concurrent_subtasks=1,  # single-threaded: _SequencedChatClient is not thread-safe
        ),
    )

    result = runner.run("What is LangGraph?")

    assert result["status"] == "completed"
    assert result["curator_output"]["title"] == "LangGraph Research"
    assert "report_path" in result


# ── R-107: execution_trace.md generation ────────────────────────────────────


def test_execution_trace_md_generated_after_successful_flow(tmp_path):
    """After a successful web research flow, execution_trace.md must be written."""
    _service, _config_path, workspace = configured_service(tmp_path)

    mock_gateway = MagicMock()
    mock_gateway.call.return_value = MagicMock(
        status="ok",
        data={"results": [{"title": "Test", "url": "https://example.com", "content": "Test content"}]},
    )

    chat_completions = [
        _make_planner_response("Trace Test", ["Find info about X."]),
        _make_tool_plan_response("Find info about X"),
        _make_executor_response("st_1", "X is a thing.", "https://example.com/x"),
        _make_supervisor_response("curate", "Enough for curation.", saturation=True),
        _make_curator_response("Trace Test", "X is a thing. Here is more detail."),
    ]

    mock_chat = _SequencedChatClient(chat_completions)

    runner = StateGraphRunner(
        config=RunnerConfig(
            workspace=str(workspace),
            chat_models=_make_chat_models(mock_chat),
            tool_gateway=mock_gateway,
            max_retrieval_rounds=3,
            max_concurrent_subtasks=1,
        ),
    )

    result = runner.run("What is X?")
    task_id = result["task_id"]

    trace_path = workspace / "tasks" / task_id / "execution_trace.md"
    assert trace_path.exists(), f"execution_trace.md not found at {trace_path}"

    content = trace_path.read_text(encoding="utf-8")

    # Must contain a Mermaid flowchart
    assert "```mermaid" in content
    assert "flowchart" in content

    # Must mention the research question and title
    assert result["curator_output"]["title"] in content

    # Must mention key execution steps
    assert "st_1" in content


def test_execution_trace_md_generated_after_failed_flow(tmp_path):
    """After a failed flow, execution_trace.md should still be written for debugging."""
    _service, _config_path, workspace = configured_service(tmp_path)

    mock_gateway = MagicMock()
    mock_gateway.call.return_value = MagicMock(
        status="ok",
        data={"results": [{"title": "Test", "url": "https://example.com", "content": "Test content"}]},
    )

    # Planner + executor but supervisor routes to fail
    chat_completions = [
        _make_planner_response("Fail Trace", ["Find nothing."]),
        _make_tool_plan_response("Find nothing"),
        _make_executor_response("st_1", "Nothing found.", "https://example.com/nope"),
        _make_supervisor_response("fail", "No usable findings.", saturation=False),
    ]

    mock_chat = _SequencedChatClient(chat_completions)

    runner = StateGraphRunner(
        config=RunnerConfig(
            workspace=str(workspace),
            chat_models=_make_chat_models(mock_chat),
            tool_gateway=mock_gateway,
            max_retrieval_rounds=3,
            max_concurrent_subtasks=1,
        ),
    )

    result = runner.run("What is nothing?")
    task_id = result["task_id"]

    trace_path = workspace / "tasks" / task_id / "execution_trace.md"
    assert trace_path.exists(), f"execution_trace.md not found after failed flow at {trace_path}"

    content = trace_path.read_text(encoding="utf-8")
    assert "```mermaid" in content
    assert "fail" in content.lower()


def test_research_executor_empty_tool_calls_returns_failed(tmp_path):
    """When LLM returns empty tool_calls, executor should return failed without synthesis."""
    mock_gateway = MagicMock()
    mock_gateway.call.return_value = MagicMock(
        status="ok",
        data={"results": []},
    )

    executor = ResearchExecutor(tool_gateway=mock_gateway, max_concurrent_subtasks=1)
    state = create_initial_state(original_question="What is LangGraph?")
    state["research_title"] = "LangGraph Research"
    state["subtasks"] = [ResearchSubtask(subtask_id="st_1", question="Find architecture overview.")]

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


def test_route_after_supervise_redirects_revise_plan_at_max_rounds(tmp_path):
    """_route_after_supervise should redirect revise_plan when retrieval_round >= max, not just continue_execution."""
    _service, _config_path, workspace = configured_service(tmp_path)

    mock_gateway = MagicMock()
    runner = StateGraphRunner(
        config=RunnerConfig(
            workspace=str(workspace),
            chat_models=_make_chat_models(_SequencedChatClient([])),
            tool_gateway=mock_gateway,
            max_retrieval_rounds=2,
            max_concurrent_subtasks=3,
        ),
    )

    state = create_initial_state(original_question="test")
    state["findings"] = [Finding(finding_id="f_1", subtask_id="st_1", text="Found something.", source_ids=["src_1"])]
    state["sources"] = [WebSource(source_id="src_1", title="Source 1", url="https://example.com", fetched_at=utc_now_iso())]
    state["retrieval_round"] = 3  # >= max_retrieval_rounds
    state["last_supervisor_output"] = SupervisorOutput(
        route="revise_plan", reason="Need more.",
        next_subtask_ids=[], skip_subtask_ids=[], plan_revision_request="More details needed.",
        research_gaps=[], saturation=False,
    )

    # revise_plan at max rounds + findings → curate
    result = route_after_supervise(state, max_retrieval_rounds=2)
    assert result == "curate", f"expected revise_plan→curate at max rounds, got: {result}"

    # When no findings, should redirect to "fail"
    state_no_findings = create_initial_state(original_question="test")
    state_no_findings["retrieval_round"] = 3
    state_no_findings["last_supervisor_output"] = SupervisorOutput(
        route="revise_plan", reason="Need more.",
        next_subtask_ids=[], skip_subtask_ids=[], plan_revision_request="More details needed.",
        research_gaps=[], saturation=False,
    )
    result2 = route_after_supervise(state_no_findings, max_retrieval_rounds=2)
    assert result2 == "fail", f"expected revise_plan→fail when no findings, got: {result2}"


def test_route_after_supervise_preserves_curate_and_fail_at_any_round(tmp_path):
    """_route_after_supervise should pass through 'curate' and 'fail' unchanged regardless of round."""
    _service, _config_path, workspace = configured_service(tmp_path)

    runner = StateGraphRunner(
        config=RunnerConfig(
            workspace=str(workspace),
            chat_models=_make_chat_models(_SequencedChatClient([])),
            tool_gateway=MagicMock(),
            max_retrieval_rounds=2,
            max_concurrent_subtasks=3,
        ),
    )

    state = create_initial_state(original_question="test")
    state["retrieval_round"] = 3  # >= max

    # curate and fail should always pass through unchanged
    state["last_supervisor_output"] = SupervisorOutput(
        route="curate", reason="Done.",
        next_subtask_ids=[], skip_subtask_ids=[], plan_revision_request=None,
        research_gaps=[], saturation=True,
    )
    assert route_after_supervise(state, max_retrieval_rounds=2) == "curate"

    state["last_supervisor_output"] = SupervisorOutput(
        route="fail", reason="No results.",
        next_subtask_ids=[], skip_subtask_ids=[], plan_revision_request=None,
        research_gaps=[], saturation=False,
    )
    assert route_after_supervise(state, max_retrieval_rounds=2) == "fail"


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
        config=RunnerConfig(
            workspace=str(workspace),
            chat_models=_make_chat_models(mock_chat),
            tool_gateway=mock_gateway,
            max_retrieval_rounds=3,
            max_concurrent_subtasks=1,  # single-threaded: _SequencedChatClient is not thread-safe
        ),
    )

    result = runner.run("test question")

    # Should complete: empty next_subtask_ids → redirect to curate (findings exist)
    assert result["status"] == "completed", f"got {result.get('status')}: {result.get('error', {})}"


# ── R-92 / R-93: _merge_subtasks reducer contract ──────────────────────


def test_merge_subtasks_updates_status_preserving_question():
    """Reducer should update status from right while preserving question from left."""
    existing = [
        ResearchSubtask(subtask_id="st_1", question="What is X?", status="pending"),
        ResearchSubtask(subtask_id="st_2", question="What is Y?", status="pending"),
    ]
    # Node returns only the changed subtask (new object, immutable pattern)
    updates = [
        ResearchSubtask(subtask_id="st_1", question="What is X?", status="completed"),
    ]
    result = _merge_subtasks(existing, updates)
    assert len(result) == 2
    st1 = next(s for s in result if s.subtask_id == "st_1")
    assert st1.status == "completed"
    assert st1.question == "What is X?"


def test_merge_subtasks_appends_new_subtask_ids():
    """Reducer should append subtasks whose subtask_id is not in the left list."""
    existing = [ResearchSubtask(subtask_id="st_1", question="Q1", status="completed")]
    new = [ResearchSubtask(subtask_id="st_2", question="Q2", status="pending")]
    result = _merge_subtasks(existing, new)
    assert len(result) == 2


def test_merge_subtasks_does_not_mutate_input_lists():
    """Reducer must return a new list — not mutate the left (existing) list."""
    existing = [ResearchSubtask(subtask_id="st_1", question="Q1", status="pending")]
    updates = [ResearchSubtask(subtask_id="st_1", question="Q1", status="completed")]
    original_status = existing[0].status
    _merge_subtasks(existing, updates)
    # Original object untouched
    assert existing[0].status == original_status


def test_merge_subtasks_handles_skip_status():
    """Reducer should correctly apply supervisor's 'skipped' status."""
    existing = [ResearchSubtask(subtask_id="st_1", question="Q1", status="pending")]
    updates = [ResearchSubtask(subtask_id="st_1", question="Q1", status="skipped")]
    result = _merge_subtasks(existing, updates)
    assert result[0].status == "skipped"


# ── R-111: ResearchSubtask must be immutable (frozen=True) ─────────────


def test_research_subtask_is_immutable():
    """ResearchSubtask should be frozen — mutation should raise an error."""
    import pytest

    subtask = ResearchSubtask(subtask_id="st_1", question="What is X?", status="pending")
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError or AttributeError
        subtask.status = "completed"  # type: ignore[misc]


# ── R-110: event_subtype validation in _emit_progress_item ─────────────


def test_emit_progress_item_rejects_unknown_kind(tmp_path, caplog):
    """Unknown item kinds should be rejected with a warning log.

    Only the known event_subtype values (per ADR-0023) should be passed
    through to _emit.  Unknown kinds must log a warning and skip the emit.
    """
    import logging

    mock_gateway = MagicMock()
    mock_gateway.call.return_value = MagicMock(
        status="ok",
        data={"results": []},
    )
    mock_gateway.registry.has.return_value = True

    runner = StateGraphRunner(
        config=RunnerConfig(
            workspace=str(tmp_path),
            chat_models={},
            tool_gateway=mock_gateway,
        ),
    )
    runner._task_id = "task_20260702_120000_abc123"
    runner._event_seq = 0

    with caplog.at_level(logging.WARNING, logger="research_agent.web.state_graph"):
        # Known kind: should NOT log a warning
        runner._emit_progress_item({"kind": "tool_call", "name": "test"})
        # Unknown kind: should log a warning
        runner._emit_progress_item({"kind": "invalid_kind_xyz"})

    # Verify that the unknown kind was logged
    warnings = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    unknown_warnings = [w for w in warnings if "invalid_kind_xyz" in w or "unknown" in w.lower()]
    assert len(unknown_warnings) >= 1, f"Expected warning for unknown kind, got warnings: {warnings}"


# ── R-114: Concurrent execution with thread-safe mock ────────────────────


class _ThreadSafeChatClient:
    """Thread-safe mock chat client that serves completions from a queue.

    Uses ``queue.Queue`` for completions (thread-safe pop) and a lock for
    the prompts list, so ``ResearchExecutor`` with ``max_concurrent_subtasks
    > 1`` can call ``complete()`` from multiple threads concurrently.
    """

    def __init__(self, completions: list[str]) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        for c in completions:
            self._queue.put(c)
        self._lock = threading.Lock()
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        with self._lock:
            self.prompts.append(prompt)
        try:
            return self._queue.get(timeout=5)
        except queue.Empty:
            return ""


def test_research_executor_concurrent_subtasks_with_thread_safe_mock(tmp_path):
    """ResearchExecutor with max_concurrent_subtasks=3 must complete all subtasks.

    This test exercises the ThreadPoolExecutor multi-worker path that was
    previously untested due to _SequencedChatClient not being thread-safe.
    Uses _ThreadSafeChatClient with queue-based completions.
    """
    mock_gateway = MagicMock()
    mock_gateway.call.return_value = MagicMock(
        status="ok",
        data={"results": [{"title": "Test", "url": "https://example.com", "content": "Test content"}]},
    )
    mock_gateway.registry.has.return_value = True

    executor = ResearchExecutor(tool_gateway=mock_gateway, max_concurrent_subtasks=3)
    state = create_initial_state(original_question="Concurrent test")
    state["research_title"] = "Concurrent Research"
    state["subtasks"] = [
        ResearchSubtask(subtask_id="st_1", question="Topic A.", status="pending"),
        ResearchSubtask(subtask_id="st_2", question="Topic B.", status="pending"),
        ResearchSubtask(subtask_id="st_3", question="Topic C.", status="pending"),
    ]

    # 3 subtasks × 2 LLM calls each (tool plan + synthesis)
    completions = []
    for i in range(3):
        sid = f"st_{i + 1}"
        completions.append(json.dumps({
            "tool_calls": [{"name": "web.search", "arguments": {"query": f"query {i}", "max_results": 5}}],
        }))
        completions.append(json.dumps({
            "subtask_id": sid,
            "status": "completed",
            "findings": [{
                "finding_id": f"f_{sid}",
                "subtask_id": sid,
                "text": f"Finding for {sid}.",
                "source_ids": [f"src_{sid}"],
            }],
            "sources": [{
                "source_id": f"src_{sid}",
                "title": f"Source for {sid}",
                "url": f"https://example.com/{sid}",
                "fetched_at": utc_now_iso(),
            }],
            "failure_reason": None,
        }))

    mock_chat = _ThreadSafeChatClient(completions)
    outputs = executor.execute(state, ["st_1", "st_2", "st_3"], chat_model=mock_chat)

    assert len(outputs) == 3
    assert all(o.status == "completed" for o in outputs)
    assert len(mock_chat.prompts) == 6  # 3 tool plan + 3 synthesis


# ── R-97: RunnerConfig dataclass for parameter grouping ────────────────


def test_runner_config_encapsulates_all_params(tmp_path):
    """RunnerConfig bundles all StateGraphRunner init params into one object."""
    mock_gateway = MagicMock()
    mock_gateway.call.return_value = MagicMock(status="ok", data={"results": []})
    mock_gateway.registry.has.return_value = True

    config = RunnerConfig(
        workspace=str(tmp_path),
        chat_models={"planner": MagicMock(), "executor": MagicMock(),
                     "supervisor": MagicMock(), "curator": MagicMock()},
        tool_gateway=mock_gateway,
        max_retrieval_rounds=5,
        max_concurrent_subtasks=2,
    )
    runner = StateGraphRunner(config=config)
    assert runner.max_retrieval_rounds == 5
    assert runner.max_concurrent_subtasks == 2
    assert runner.executor is not None