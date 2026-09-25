"""Per-subtask ExecutorOutput persistence and re-entry skip semantics (ADR-0056).

The execute node is checkpointed only as a whole (node-level SqliteSaver), so
a crash mid-node would otherwise lose every already-finished subtask in the
batch. The Executor Output Log appends each result the moment it completes and
lets a re-entered execute skip subtasks whose results never reached the
Blackboard. All tests are offline and deterministic.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from research_agent.core.providers import ToolCallResult
from research_agent.web.executor import ExecutorOutputLog, ResearchExecutor
from research_agent.web.schemas import (
    ExecutorOutput,
    Finding,
    ResearchSubtask,
    WebResearchStateDict,
    WebSource,
    create_initial_state,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _DispatchChatClient:
    """Routes complete_tool calls to per-question scripted responses.

    Executor prompts embed each subtask's question, so dispatching on the
    question text gives per-subtask control: which subtasks run, with what
    delay, and which must never be called at all.
    """

    def __init__(self) -> None:
        self._scripts: dict[str, list[ToolCallResult]] = {}
        self._delays: dict[str, float] = {}
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def script(self, question: str, responses: list[ToolCallResult], *, delay: float = 0.0) -> None:
        self._scripts[question] = list(responses)
        self._delays[question] = delay

    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        raise AssertionError("executor path uses tool calling only")

    def complete_tool(self, prompt: str, *, tool_name: str, tool_schema: dict[str, Any]) -> ToolCallResult:
        matched = [q for q in self._scripts if q in prompt]
        if not matched:
            raise AssertionError(f"Unexpected LLM call, no scripted question in prompt: {prompt[:120]}")
        question = matched[0]
        with self._lock:
            self.calls.append(question)
            response = self._scripts[question].pop(0)
        time.sleep(self._delays.get(question, 0.0))
        return response


def _plan_result(query: str) -> ToolCallResult:
    return ToolCallResult(
        name="executor_tool_plan",
        arguments={"tool_calls": [{"name": "web.search", "arguments": {"query": query}}]},
    )


def _synthesis_result(subtask_id: str, finding_text: str) -> ToolCallResult:
    return ToolCallResult(
        name="executor_synthesis",
        arguments={
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
                "title": "Source",
                "url": f"https://example.com/{subtask_id}",
                "fetched_at": "2026-09-25T00:00:00Z",
            }],
        },
    )


def _seeded_output(subtask_id: str) -> ExecutorOutput:
    return ExecutorOutput(
        subtask_id=subtask_id,
        status="completed",
        findings=[Finding(
            finding_id=f"f_{subtask_id}",
            subtask_id=subtask_id,
            text=f"Seeded finding for {subtask_id}",
            source_ids=[f"src_{subtask_id}"],
        )],
        sources=[WebSource(
            source_id=f"src_{subtask_id}",
            title="Seeded",
            url=f"https://example.com/{subtask_id}",
            fetched_at="2026-09-25T00:00:00Z",
        )],
    )


def _state_with(*pairs: tuple[str, str]) -> WebResearchStateDict:
    state = create_initial_state(original_question="root question")
    state["subtasks"] = [ResearchSubtask(subtask_id=sid, question=q) for sid, q in pairs]
    return state


def _mock_gateway() -> MagicMock:
    gateway = MagicMock()
    gateway.call.return_value = MagicMock(
        status="ok",
        data={"results": [{"title": "Test", "url": "https://example.com", "content": "Test content"}]},
    )
    return gateway


# ---------------------------------------------------------------------------
# ExecutorOutputLog unit behavior
# ---------------------------------------------------------------------------


def test_output_log_roundtrip_last_record_wins_and_corrupt_lines_skipped(tmp_path):
    log = ExecutorOutputLog(tmp_path / "tasks" / "task_x" / "artifacts" / "executor_outputs.jsonl")
    log.append(_seeded_output("st_1"))
    # A crash mid-write can leave a truncated line — the reader must skip it.
    log.path.write_text(
        log.path.read_text(encoding="utf-8") + '{"subtask_id": "st_trunca\n',
        encoding="utf-8",
    )
    failed_rerun = ExecutorOutput(
        subtask_id="st_1", status="failed", findings=[], sources=[], failure_reason="rerun failed",
    )
    log.append(failed_rerun)
    log.append(_seeded_output("st_2"))

    latest = log.latest_by_subtask()

    assert set(latest) == {"st_1", "st_2"}
    assert latest["st_1"].status == "failed"  # last record per subtask wins
    assert latest["st_1"].failure_reason == "rerun failed"
    assert latest["st_2"].status == "completed"
    assert latest["st_2"].findings[0].text == "Seeded finding for st_2"


def test_output_log_append_failure_never_raises(tmp_path):
    directory = tmp_path / "not-a-file"
    directory.mkdir()
    log = ExecutorOutputLog(directory)

    log.append(_seeded_output("st_1"))  # path is a directory → OSError → warning only

    assert log.latest_by_subtask() == {}


def test_output_log_missing_file_returns_empty(tmp_path):
    log = ExecutorOutputLog(tmp_path / "never" / "written.jsonl")

    assert log.latest_by_subtask() == {}


# ---------------------------------------------------------------------------
# execute() persistence + re-entry semantics
# ---------------------------------------------------------------------------


def test_execute_appends_each_output_as_it_completes(tmp_path):
    log = ExecutorOutputLog(tmp_path / "executor_outputs.jsonl")
    state = _state_with(("st_fast", "fast question"), ("st_slow", "slow question"))
    chat = _DispatchChatClient()
    chat.script("fast question", [_plan_result("fast"), _synthesis_result("st_fast", "fast finding")])
    chat.script(
        "slow question",
        [_plan_result("slow"), _synthesis_result("st_slow", "slow finding")],
        delay=0.3,
    )
    observed: dict[str, Any] = {}

    def on_progress(item: dict[str, Any]) -> None:
        if item["kind"] == "subtask_completed" and item["subtask_id"] == "st_fast":
            # While st_slow is still running, st_fast's result must already be
            # on disk — that immediacy is the whole point of the log.
            observed["fast_lines_at_completion"] = log.path.read_text(encoding="utf-8")
    executor = ResearchExecutor(
        tool_gateway=_mock_gateway(), max_concurrent_subtasks=2, on_progress=on_progress
    )

    outputs = executor.execute(state, ["st_fast", "st_slow"], chat, output_log=log)

    assert sorted(o.subtask_id for o in outputs) == ["st_fast", "st_slow"]
    assert all(o.status == "completed" for o in outputs)
    assert "st_fast" in observed["fast_lines_at_completion"]
    lines = [line for line in log.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2


def test_execute_reuses_persisted_output_missing_from_state(tmp_path):
    log = ExecutorOutputLog(tmp_path / "executor_outputs.jsonl")
    log.append(_seeded_output("st_1"))  # completed after the last checkpoint, never merged
    state = _state_with(("st_1", "question one"), ("st_2", "question two"))
    chat = _DispatchChatClient()
    chat.script("question two", [_plan_result("q2"), _synthesis_result("st_2", "fresh finding")])
    executor = ResearchExecutor(tool_gateway=_mock_gateway())

    outputs = executor.execute(state, ["st_1", "st_2"], chat, output_log=log)

    # st_1 was never re-run — its LLM was not called.
    assert "question one" not in chat.calls
    by_id = {o.subtask_id: o for o in outputs}
    assert by_id["st_1"].findings[0].text == "Seeded finding for st_1"
    assert by_id["st_2"].findings[0].text == "fresh finding"
    # Only the newly executed subtask appended a line.
    lines = [line for line in log.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2


def test_execute_reruns_subtask_already_merged_in_state(tmp_path):
    log = ExecutorOutputLog(tmp_path / "executor_outputs.jsonl")
    seeded = _seeded_output("st_1")
    log.append(seeded)
    state = _state_with(("st_1", "question one"))
    # The Blackboard already merged st_1's earlier result, so a fresh
    # assignment is a Supervisor decision to run again — not crash recovery.
    state["executor_outputs"] = [seeded]
    chat = _DispatchChatClient()
    chat.script("question one", [_plan_result("again"), _synthesis_result("st_1", "second-run finding")])
    executor = ResearchExecutor(tool_gateway=_mock_gateway())

    outputs = executor.execute(state, ["st_1"], chat, output_log=log)

    assert "question one" in chat.calls
    assert outputs[0].findings[0].text == "second-run finding"
    lines = [line for line in log.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2  # seeded + second run


def test_execute_without_log_behaves_as_before(tmp_path):
    state = _state_with(("st_1", "question one"))
    chat = _DispatchChatClient()
    chat.script("question one", [_plan_result("q"), _synthesis_result("st_1", "finding")])
    executor = ResearchExecutor(tool_gateway=_mock_gateway())

    outputs = executor.execute(state, ["st_1"], chat)

    assert outputs[0].status == "completed"
    assert list(tmp_path.rglob("executor_outputs.jsonl")) == []


# ---------------------------------------------------------------------------
# Graph-level re-entry (wiring through _execute_node, R-292)
# ---------------------------------------------------------------------------


def test_execute_node_reentry_reuses_log_without_rerunning_subtasks(tmp_path):
    """A crash after subtask completion but before the node returned means the
    next graph run re-enters _execute_node with a pre-execute state. The node
    must route through the output log and skip the finished subtask."""
    from research_agent.web.graph import GraphContext, _execute_node

    task_id = "task_20260925_000000_reentry"
    workspace_root = tmp_path
    chat = _DispatchChatClient()
    chat.script("the only question", [_plan_result("q"), _synthesis_result("st_1", "first run finding")])
    executor = ResearchExecutor(tool_gateway=_mock_gateway())
    ctx = GraphContext(
        chat_models={"executor": chat},
        executor=executor,
        max_retrieval_rounds=3,
        task_id=task_id,
        workspace=str(workspace_root),
        _emit=lambda *args, **kwargs: None,
        _save_llm_call_artifact=lambda *args, **kwargs: None,
        _save_source_snapshots=lambda *args, **kwargs: None,
    )

    fresh_state = _state_with(("st_1", "the only question"))
    first = _execute_node(fresh_state, ctx)
    assert first["executor_outputs"][0].findings[0].text == "first run finding"
    calls_after_first = len(chat.calls)

    # "Crash": the checkpoint still holds the pre-execute state (no
    # executor_outputs merged). Re-enter the node with that state.
    second = _execute_node(_state_with(("st_1", "the only question")), ctx)

    assert len(chat.calls) == calls_after_first  # subtask not re-run
    assert second["executor_outputs"][0].subtask_id == "st_1"
    assert second["executor_outputs"][0].findings[0].text == "first run finding"
    log_lines = (workspace_root / "tasks" / task_id / "artifacts" / "executor_outputs.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len([line for line in log_lines if line.strip()]) == 1
