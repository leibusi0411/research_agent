"""Tests for EventStream — unified progress event transport.

Covers S1 (C1-C4): ProgressEvent schema, _emit dual-write, events() async iterator,
and seq deduplication.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from research_agent.core.bus import Bus
from research_agent.core.config import InitConfigRequest
from research_agent.core.ids import generate_task_id, utc_now_iso
from research_agent.core.service import CoreService
from research_agent.core.workspace import Workspace
from research_agent.web.schemas import ProgressEvent
from research_agent.web.state_graph import RunnerConfig, StateGraphRunner
from research_agent.web.tools import ToolGateway


def _configured_workspace(tmp_path: Path) -> tuple[Path, Workspace]:
    """Create a configured workspace directory with minimal config."""
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
    return config_path, Workspace(workspace)


def _make_runner(workspace: Workspace, bus: Bus | None = None) -> StateGraphRunner:
    """Create a runner with mock chat models and tool gateway."""
    mock_chat = MagicMock()
    mock_chat.complete.return_value = "{}"
    mock_registry = MagicMock()
    mock_registry.has.return_value = True
    mock_gateway = MagicMock()
    mock_gateway.registry = mock_registry
    mock_gateway.call.return_value = MagicMock(status="ok", data="", error=None, message="")
    return StateGraphRunner(
        config=RunnerConfig(
            workspace=str(workspace.root),
            chat_models={"planner": mock_chat, "executor": mock_chat, "supervisor": mock_chat, "curator": mock_chat},
            tool_gateway=mock_gateway,
            workspace_obj=workspace,
            bus=bus,
        ),
    )


class TestProgressEventSchema:
    """C1: ProgressEvent carries seq and event_subtype in serialised output."""

    def test_to_dict_includesseq_and_subtype(self):
        """seq and event_subtype appear in the serialised dict."""
        created_at = utc_now_iso()
        event = ProgressEvent(
            task_id="t1",
            mode="web",
            phase="web_execution",
            event_type="progress",
            created_at=created_at,
            message="searching",
            details={"items": []},
            seq=42,
            event_subtype="tool_call",
        )
        d = event.to_dict()
        assert d["task_id"] == "t1"
        assert d["mode"] == "web"
        assert d["phase"] == "web_execution"
        assert d["event_type"] == "progress"
        assert d["event_subtype"] == "tool_call"
        assert d["seq"] == 42
        assert d["details"] == {"items": []}

    def test_event_subtype_is_none_for_phase_boundary_events(self):
        """Phase-boundary events (started/completed/failed) omit subtype."""
        event = ProgressEvent(
            task_id="t1",
            mode="web",
            phase="web_execution",
            event_type="completed",
            created_at=utc_now_iso(),
            message="done.",
            details={"items": []},
            seq=5,
            event_subtype=None,
        )
        d = event.to_dict()
        assert d["event_subtype"] is None
        assert d["seq"] == 5

    def test_backward_compatible_without_new_fields(self):
        """Callers that don't pass new fields still get valid output (no crash)."""
        event = ProgressEvent(
            task_id="t1",
            mode="web",
            phase="web_planning",
            event_type="started",
            created_at=utc_now_iso(),
            message="planning",
            details={"items": []},
        )
        d = event.to_dict()
        assert d["task_id"] == "t1"
        assert d["event_subtype"] is None
        assert d["seq"] == 0


async def _drain_one(bus: Bus, channel: str, out: list[dict]) -> None:
    """Read one event from *bus* on *channel* and append to *out*."""
    async for payload in bus.subscribe(channel):
        out.append(json.loads(payload["data"]))
        break


class TestEventStreamAsyncIterator:
    """C3: events() AsyncIterator - file replay, queue switch, seq dedup."""

    @pytest.mark.asyncio
    async def test_events_replays_file_events(self, tmp_path):
        """File replay yields all events persisted before consumer connected."""
        _, workspace = _configured_workspace(tmp_path)
        bus = Bus()
        runner = _make_runner(workspace, bus=bus)

        task_id = generate_task_id()
        workspace.create_task_folder(
            task_id,
            task_metadata={"task_id": task_id, "mode": "web", "question": "q", "created_at": utc_now_iso()},
            result={"task_id": task_id, "mode": "web", "question": "q", "status": "running", "created_at": utc_now_iso()},
        )
        runner._task_id = task_id

        # Write 3 events to file BEFORE consumer connects
        runner._emit(task_id, "web_planning", "started", "event_1")
        runner._emit(task_id, "web_planning", "completed", "event_2")
        runner._emit(task_id, "web_execution", "started", "event_3")

        # Connect consumer — should replay all 3 from file,
        # then block waiting for bus. Use timeout to stop after replay.
        collected = []
        async_gen = runner.events()

        for _ in range(3):
            evt = await asyncio.wait_for(async_gen.__anext__(), timeout=2)
            # events() yields {"data": json_string} dicts (sse_starlette format)
            parsed = json.loads(evt["data"])
            collected.append(parsed)

        assert [e["message"] for e in collected] == ["event_1", "event_2", "event_3"]
        assert [e["seq"] for e in collected] == [1, 2, 3]
        await async_gen.aclose()

    @pytest.mark.asyncio
    async def test_events_queue_receives_post_connect_event(self, tmp_path):
        """After connecting, events arrive via the live Bus (mycode pattern)."""
        _, workspace = _configured_workspace(tmp_path)
        bus = Bus()
        runner = _make_runner(workspace, bus=bus)

        task_id = generate_task_id()
        workspace.create_task_folder(
            task_id,
            task_metadata={"task_id": task_id, "mode": "web", "question": "q", "created_at": utc_now_iso()},
            result={"task_id": task_id, "mode": "web", "question": "q", "status": "running", "created_at": utc_now_iso()},
        )
        runner._task_id = task_id

        # Pre-emit 1 event to file
        runner._emit(task_id, "web_planning", "started", "before_connect")

        # Collect from events() concurrently
        collected: list[dict] = []
        async def _consume():
            async for evt in runner.events():
                collected.append(json.loads(evt["data"]))
                if len(collected) >= 2:
                    break

        consumer = asyncio.ensure_future(_consume())
        # Let consumer start (file replay happens synchronously on first await)
        await asyncio.sleep(0.05)

        # Publish a live event after consumer is already waiting on bus
        await bus.publish(f"task.{task_id}",
            task_id=task_id, mode="web", phase="web_execution",
            event_type="progress", event_subtype="tool_call",
            created_at=utc_now_iso(), message="after_connect",
            seq=42, details={"items": []},
        )

        await asyncio.wait_for(consumer, timeout=2)

        assert collected[0]["message"] == "before_connect"
        assert collected[0]["seq"] == 1
        assert collected[1]["message"] == "after_connect"
        assert collected[1]["seq"] == 42


class TestProgressItemSubtype:
    """C4: _emit_progress_item sets event_subtype from item kind."""

    def test_progress_items_have_correct_subtype(self, tmp_path):
        """Each progress item kind maps to the correct event_subtype."""
        _, workspace = _configured_workspace(tmp_path)
        runner = _make_runner(workspace)

        task_id = generate_task_id()
        workspace.create_task_folder(
            task_id,
            task_metadata={"task_id": task_id, "mode": "web", "question": "q", "created_at": utc_now_iso()},
            result={"task_id": task_id, "mode": "web", "question": "q", "status": "running", "created_at": utc_now_iso()},
        )
        runner._task_id = task_id

        # Simulate _emit_progress_item calls from ResearchExecutor
        runner._emit_progress_item({"kind": "tool_call", "name": "web.search", "input": "query"})
        runner._emit_progress_item({"kind": "finding", "text": "a finding", "subtask_id": "st_1"})
        runner._emit_progress_item({"kind": "source", "title": "A Source", "url": "https://example.com"})
        runner._emit_progress_item({"kind": "subtask_completed", "subtask_id": "st_1", "question": "q?"})

        task_dir = workspace.task_dir(task_id)
        events_text = (task_dir / "events.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in events_text.strip().splitlines()]

        subtypes = {e["event_subtype"]: e["event_subtype"] for e in events}
        assert subtypes.get("tool_call") == "tool_call"
        assert subtypes.get("finding") == "finding"
        assert subtypes.get("source") == "source"
        assert subtypes.get("subtask_completed") == "subtask_completed"


class TestEmitDualWrite:
    """C2: _emit writes to events.jsonl (always) and Bus (when configured)."""

    def test_emit_writes_to_file_when_no_queue(self, tmp_path):
        """When no consumer has connected, _emit only writes to file."""
        _, workspace = _configured_workspace(tmp_path)
        runner = _make_runner(workspace)

        task_id = generate_task_id()
        workspace.create_task_folder(
            task_id,
            task_metadata={"task_id": task_id, "mode": "web", "question": "q", "created_at": utc_now_iso()},
            result={"task_id": task_id, "mode": "web", "question": "q", "status": "running", "created_at": utc_now_iso()},
        )
        runner._task_id = task_id

        runner._emit(task_id, "web_planning", "started", "planning starts")

        task_dir = workspace.task_dir(task_id)
        events_text = (task_dir / "events.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in events_text.strip().splitlines()]
        target = [e for e in events if e["message"] == "planning starts"]
        assert len(target) == 1
        assert target[0]["seq"] == 1

    def test_emit_incrementsseq(self, tmp_path):
        """Each _emit call increments the seq counter."""
        _, workspace = _configured_workspace(tmp_path)
        runner = _make_runner(workspace)

        task_id = generate_task_id()
        workspace.create_task_folder(
            task_id,
            task_metadata={"task_id": task_id, "mode": "web", "question": "q", "created_at": utc_now_iso()},
            result={"task_id": task_id, "mode": "web", "question": "q", "status": "running", "created_at": utc_now_iso()},
        )
        runner._task_id = task_id

        runner._emit(task_id, "web_planning", "started", "first")
        runner._emit(task_id, "web_planning", "completed", "second")
        runner._emit(task_id, "web_execution", "started", "third")

        task_dir = workspace.task_dir(task_id)
        events_text = (task_dir / "events.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in events_text.strip().splitlines()]
        custom = [e for e in events if e["message"] in ("first", "second", "third")]
        assert [e["seq"] for e in custom] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_emit_publishes_to_bus_when_active(self, tmp_path):
        """When bus is configured, events arrive at subscribers."""
        _, workspace = _configured_workspace(tmp_path)
        bus = Bus()
        runner = _make_runner(workspace, bus=bus)

        task_id = generate_task_id()
        workspace.create_task_folder(
            task_id,
            task_metadata={"task_id": task_id, "mode": "web", "question": "q", "created_at": utc_now_iso()},
            result={"task_id": task_id, "mode": "web", "question": "q", "status": "running", "created_at": utc_now_iso()},
        )
        runner._task_id = task_id

        # Start subscriber first
        collected: list[dict] = []
        async def _consume_one():
            async for payload in bus.subscribe(f"task.{task_id}"):
                collected.append(json.loads(payload["data"]))
                break

        sub_task = asyncio.ensure_future(_consume_one())
        await asyncio.sleep(0)  # let subscriber register

        # Publish via bus async path
        await bus.publish(f"task.{task_id}",
            task_id=task_id, mode="web", phase="web_execution",
            event_type="progress", event_subtype="tool_call",
            message="tool_call search", seq=1, details={"items": []},
            created_at=utc_now_iso(),
        )

        await asyncio.wait_for(sub_task, timeout=2)

        # File persistence still works via _emit
        runner._emit(task_id, "web_execution", "progress", "tool_call search",
                     items=[{"kind": "tool_call", "name": "web.search", "input": "test"}])

        task_dir = workspace.task_dir(task_id)
        events_text = (task_dir / "events.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in events_text.strip().splitlines()]
        target = [e for e in events if e["message"] == "tool_call search"]
        assert len(target) == 1

        assert len(collected) >= 1
        assert collected[0]["phase"] == "web_execution"
        assert collected[0]["seq"] == 1


class TestTaskResultEvent:
    """T1: task_result event type — schema, emission, and persistence."""

    def test_task_result_event_type_in_schema(self):
        """ProgressEvent accepts event_type='task_result' and serialises correctly."""
        created_at = utc_now_iso()
        event = ProgressEvent(
            task_id="t1",
            mode="web",
            phase="web_curation",
            event_type="task_result",
            created_at=created_at,
            message="Task completed.",
            details={
                "items": [{"kind": "status", "task_id": "t1", "status": "completed", "mode": "web"}]
            },
            seq=99,
            event_subtype=None,
        )
        d = event.to_dict()
        assert d["event_type"] == "task_result"
        assert d["phase"] == "web_curation"
        assert d["seq"] == 99
        assert d["details"]["items"][0]["kind"] == "status"
        assert d["details"]["items"][0]["status"] == "completed"

    def test_emit_task_result_writes_to_file(self, tmp_path):
        """_emit with event_type='task_result' persists to events.jsonl correctly."""
        _, workspace = _configured_workspace(tmp_path)
        runner = _make_runner(workspace)

        task_id = generate_task_id()
        workspace.create_task_folder(
            task_id,
            task_metadata={"task_id": task_id, "mode": "web", "question": "q", "created_at": utc_now_iso()},
            result={"task_id": task_id, "mode": "web", "question": "q", "status": "running", "created_at": utc_now_iso()},
        )
        runner._task_id = task_id

        runner._emit(task_id, "web_curation", "task_result", "Task completed.",
                     items=[{"kind": "status", "task_id": task_id, "status": "completed", "mode": "web"}])

        task_dir = workspace.task_dir(task_id)
        events_text = (task_dir / "events.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in events_text.strip().splitlines()]
        assert events[-1]["event_type"] == "task_result"
        assert events[-1]["message"] == "Task completed."
        assert events[-1]["details"]["items"][0]["status"] == "completed"

    def test_local_persist_task_emits_task_result(self, tmp_path):
        """local_research._persist_task emits a task_result event as the last line."""
        from research_agent.core.local_research import _persist_task
        from research_agent.core.tasks import TaskStore

        _, workspace = _configured_workspace(tmp_path)
        task_store = TaskStore(workspace.root / "task_store.db")
        task_id = generate_task_id()
        created_at = utc_now_iso()
        question = "test question"
        result = {
            "task_id": task_id,
            "mode": "local",
            "question": question,
            "status": "completed",
            "created_at": created_at,
            "completed_at": utc_now_iso(),
            "local_results": [],
        }

        _persist_task(workspace, task_store, task_id, question, created_at, result,
                      completed_items=[{"kind": "source", "path": "/vault/note.md"}])

        task_dir = workspace.task_dir(task_id)
        events_text = (task_dir / "events.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in events_text.strip().splitlines()]
        # The last event should be task_result
        assert events[-1]["event_type"] == "task_result"
        assert events[-1]["mode"] == "local"
        # The completed event should still be present
        completed_events = [e for e in events if e["event_type"] == "completed"]
        assert len(completed_events) == 1


    @pytest.mark.asyncio
    async def test_events_file_replay_then_bus_live(self, tmp_path):
        """File replay + bus live path: events() replays file then streams from bus."""
        _, workspace = _configured_workspace(tmp_path)
        bus = Bus()
        runner = _make_runner(workspace, bus=bus)

        task_id = generate_task_id()
        workspace.create_task_folder(
            task_id,
            task_metadata={"task_id": task_id, "mode": "web", "question": "q", "created_at": utc_now_iso()},
            result={"task_id": task_id, "mode": "web", "question": "q", "status": "running", "created_at": utc_now_iso()},
        )
        runner._task_id = task_id

        # Emit one event to file pre-connect
        runner._emit(task_id, "web_curation", "task_result", "Task completed.",
                     items=[{"kind": "status", "task_id": task_id, "status": "completed", "mode": "web"}])

        collected: list[dict] = []
        async def _consume():
            async for evt in runner.events():
                collected.append(json.loads(evt["data"]))
                if len(collected) >= 2:
                    break

        consumer = asyncio.ensure_future(_consume())
        await asyncio.sleep(0.05)

        # First event: file replay
        assert collected[0]["event_type"] == "task_result"

        # Publish a live event while consumer is active on bus
        await bus.publish(f"task.{task_id}",
            task_id=task_id, mode="web", phase="web_planning",
            event_type="completed", message="post_connect_event",
            seq=42, details={"items": []},
            created_at=utc_now_iso(),
        )

        await asyncio.wait_for(consumer, timeout=2)

        assert collected[1]["message"] == "post_connect_event"


class TestPrintWebEvent:
    """R-83: CLI output formatting for _print_web_event and _first_item."""

    @staticmethod
    def _capture_output(event: dict) -> str:
        """Call _print_web_event and return captured stdout as a string."""
        import io
        import sys

        from research_agent.cli import _print_web_event

        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            _print_web_event(event)
        finally:
            sys.stdout = old_stdout
        return buf.getvalue()

    def test_first_item_returns_dict_for_normal_items(self):
        """_first_item returns the first item when it is a dict."""
        from research_agent.cli import _first_item

        event = {"details": {"items": [{"name": "web.search", "input": "test query"}]}}
        result = _first_item(event)
        assert result == {"name": "web.search", "input": "test query"}

    def test_first_item_returns_empty_dict_for_empty_items(self):
        """_first_item returns {} when items list is empty."""
        from research_agent.cli import _first_item

        event = {"details": {"items": []}}
        result = _first_item(event)
        assert result == {}

    def test_first_item_returns_empty_dict_for_non_dict_item(self):
        """_first_item returns {} when items[0] is not a dict (R-82 defence)."""
        from research_agent.cli import _first_item

        for bad_item in [None, "string", 42, ["nested_list"]]:
            event = {"details": {"items": [bad_item]}}
            result = _first_item(event)
            assert result == {}, f"_first_item should return {{}} for items[0]={bad_item!r}"

    def test_first_item_returns_empty_dict_for_missing_details(self):
        """_first_item returns {} when details or items key is missing."""
        from research_agent.cli import _first_item

        assert _first_item({}) == {}
        assert _first_item({"details": {}}) == {}

    def test_print_tool_call_event(self):
        """tool_call subtype prints [phase] tool_name: input."""
        event = {
            "phase": "web_execution",
            "event_subtype": "tool_call",
            "message": "searching",
            "details": {"items": [{"name": "web.search", "input": "latest AI news"}]},
        }
        out = self._capture_output(event)
        assert "[web_execution] web.search: latest AI news" in out

    def test_print_finding_event(self):
        """finding subtype prints [phase] finding: text (truncated to 120 chars)."""
        event = {
            "phase": "web_execution",
            "event_subtype": "finding",
            "message": "fallback",
            "details": {"items": [{"text": "AI is transforming industries worldwide"}]},
        }
        out = self._capture_output(event)
        assert "[web_execution] finding: AI is transforming industries worldwide" in out

    def test_print_finding_event_falls_back_to_message(self):
        """finding subtype falls back to message when item text is empty."""
        event = {
            "phase": "web_execution",
            "event_subtype": "finding",
            "message": "a finding was added",
            "details": {"items": [{"text": ""}]},
        }
        out = self._capture_output(event)
        assert "[web_execution] finding: a finding was added" in out

    def test_print_source_event(self):
        """source subtype prints [phase] source: title (url)."""
        event = {
            "phase": "web_execution",
            "event_subtype": "source",
            "message": "",
            "details": {"items": [{"title": "Example", "url": "https://example.com/article"}]},
        }
        out = self._capture_output(event)
        assert "[web_execution] source: Example (https://example.com/article)" in out

    def test_print_subtask_completed_event(self):
        """subtask_completed subtype prints finding/source counts."""
        event = {
            "phase": "web_execution",
            "event_subtype": "subtask_completed",
            "message": "",
            "details": {"items": [{"finding_count": 5, "source_count": 3}]},
        }
        out = self._capture_output(event)
        assert "[web_execution] subtask_done: 5 findings, 3 sources" in out

    def test_print_subtask_completed_empty_items_falls_back_to_message(self):
        """subtask_completed with empty items falls back to message text."""
        event = {
            "phase": "web_execution",
            "event_subtype": "subtask_completed",
            "message": "all done",
            "details": {"items": []},
        }
        out = self._capture_output(event)
        assert "[web_execution] all done" in out

    def test_print_subtask_failed_event(self):
        """subtask_failed subtype prints the error message."""
        event = {
            "phase": "web_execution",
            "event_subtype": "subtask_failed",
            "message": "",
            "details": {"items": [{"error": "Connection timeout"}]},
        }
        out = self._capture_output(event)
        assert "[web_execution] subtask_failed: Connection timeout" in out

    def test_print_unknown_subtype_falls_back_to_message(self):
        """Events without a recognised subtype print [phase] message."""
        event = {
            "phase": "web_planning",
            "event_subtype": None,
            "message": "Planning started.",
            "details": {"items": []},
        }
        out = self._capture_output(event)
        assert "[web_planning] Planning started." in out

    def test_print_web_event_defensive_against_bad_items(self):
        """All subtypes handle items[0] being non-dict without crashing (R-82)."""
        for subtype in ("tool_call", "finding", "source", "subtask_completed", "subtask_failed"):
            event = {
                "phase": "web_execution",
                "event_subtype": subtype,
                "message": "fallback_msg",
                "details": {"items": [None]},  # items[0] is None, not a dict
            }
            # Must not raise
            out = self._capture_output(event)
            assert out, f"subtype={subtype} should produce output, got empty"
