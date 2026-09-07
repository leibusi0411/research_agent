from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphRecursionError

from research_agent.core.errors import ResearchError
from research_agent.core.ids import generate_task_id, utc_now_iso
from research_agent.core.providers import ChatModelClient
from research_agent.core.tasks import TaskRecord, TaskStore
from research_agent.core.workspace import Workspace
from research_agent.web.executor import ResearchExecutor
from research_agent.web.graph import GraphContext, build_web_research_graph
from research_agent.web.report import write_web_report
from research_agent.web.schemas import (
    CuratorOutput,
    ExecutorOutput,
    Finding,
    PriorKnowledgeChunk,
    ProgressEvent,
    ResearchSubtask,
    WebResearchStateDict,
    WebSource,
    create_initial_state,
)
from research_agent.web.tools import ToolGateway

logger = logging.getLogger(__name__)

# R-118: Module-level set of valid event subtypes (ADR-0023).
_VALID_EVENT_SUBTYPES: frozenset[str] = frozenset({
    "tool_call", "finding", "source", "research_gap",
    "subtask_started", "subtask_completed", "subtask_failed",
})


def _count_status(subtasks: list[ResearchSubtask], status: str) -> int:
    """Count subtasks with a given status."""
    return sum(1 for s in subtasks if s.status == status)


def _extract_round(step: str) -> str:
    """Extract round number from a route_history step like 'execute_round_2'."""
    if step.startswith("execute_round_"):
        return step.split("_")[-1]
    return "?"


def _render_mermaid_flowchart(route_history: list[str]) -> list[str]:
    """Render the execution flow as a Mermaid flowchart."""
    lines: list[str] = []
    lines.append("## Execution Flow")
    lines.append("")
    lines.append("```mermaid")
    lines.append("flowchart TD")
    lines.append("    start([START]) --> plan")
    for i, step in enumerate(route_history):
        if step == "plan_revision":
            lines.append(f"    plan_rev_{i} --> execute_{i}")
        elif step.startswith("plan"):
            lines.append("    plan --> execute")
        elif step.startswith("execute"):
            round_num = _extract_round(step)
            lines.append(f"    execute_{i}[execute round {round_num}] --> supervise_{i}")
        elif step.startswith("supervise:"):
            route = step.split(":", 1)[1]
            if route == "curate":
                lines.append(f"    supervise_{i}{{supervise}} --> curate")
                lines.append("    curate --> end([END])")
            elif route == "fail":
                lines.append(f"    supervise_{i}{{supervise}} --> fail")
                lines.append("    fail --> end([END])")
            elif route == "revise_plan":
                lines.append(f"    supervise_{i}{{supervise}} --> plan_revision")
    lines.append("```")
    lines.append("")
    return lines


def _render_step_decisions(
    route_history: list[str],
    research_title: str,
    subtasks: list[ResearchSubtask],
    executor_outputs: list[ExecutorOutput],
    final_state: WebResearchStateDict,
    curator_output: CuratorOutput | None,
) -> list[str]:
    """Render the step-by-step decision trace for each route history entry."""
    revision_ids: set[str] = set(final_state.get("revision_subtask_ids", []))
    lines: list[str] = []
    lines.append("## Step-by-Step Decisions")
    lines.append("")
    for i, step in enumerate(route_history):
        if step.startswith("plan") and not step.startswith("plan_revision"):
            # R-127: only count initial-plan subtasks (exclude revision-created ones)
            initial_subtasks = [s for s in subtasks if s.subtask_id not in revision_ids]
            lines.append(f"### Step {i + 1}: Plan")
            lines.append("")
            lines.append(f"- **Title**: {research_title}")
            lines.append(f"- **Subtasks created**: {len(initial_subtasks)}")
            for st in initial_subtasks:
                lines.append(f"  - `{st.subtask_id}`: {st.question} [{st.status}]")
            lines.append("")
        elif step.startswith("execute"):
            round_num = _extract_round(step)
            lines.append(f"### Step {i + 1}: Execute (Round {round_num})")
            lines.append("")
            for eo in executor_outputs:
                lines.append(f"- **{eo.subtask_id}**: `{eo.status}`")
                if eo.failure_reason:
                    lines.append(f"  - Failure: {eo.failure_reason}")
                if eo.findings:
                    for f in eo.findings:
                        lines.append(f"  - Finding: {f.text[:120]}")
                if eo.sources:
                    for s in eo.sources:
                        lines.append(f"  - Source: [{s.title}]({s.url})")
            lines.append("")
        elif step.startswith("supervise:"):
            route = step.split(":", 1)[1]
            last_sup = final_state.get("last_supervisor_output")
            reason = last_sup.reason if last_sup else "N/A"
            gaps: list[str] = final_state.get("research_gaps", [])
            lines.append(f"### Step {i + 1}: Supervise → `{route}`")
            lines.append("")
            lines.append(f"- **Reason**: {reason}")
            if gaps:
                lines.append(f"- **Research gaps**: {', '.join(gaps)}")
            lines.append("")
        elif step == "plan_revision":
            lines.append(f"### Step {i + 1}: Plan Revision")
            lines.append("")
            last_sup = final_state.get("last_supervisor_output")
            if last_sup and last_sup.plan_revision_request:
                lines.append(f"- **Revision request**: {last_sup.plan_revision_request}")
            # R-123: use explicit revision_subtask_ids instead of fragile [-3:] heuristic
            new_sts = [s for s in subtasks if s.subtask_id in revision_ids]
            for st in new_sts:
                lines.append(f"  - New: `{st.subtask_id}`: {st.question} [{st.status}]")
            lines.append("")

    if curator_output is not None:
        lines.append("## Final Curation")
        lines.append("")
        lines.append(f"- **Title**: {curator_output.title}")
        lines.append(f"- **Summary**: {curator_output.summary[:200]}")
        lines.append(f"- **Findings in report**: {len(curator_output.findings)}")
        lines.append(f"- **Sources cited**: {len(curator_output.sources)}")
        lines.append("")
    else:
        lines.append("## Failure")
        lines.append("")
        lines.append("Research did not produce a curated output.")
        lines.append("")
    return lines


# R-97: RunnerConfig dataclass bundles all initialization parameters.
@dataclass(frozen=True)
class RunnerConfig:
    workspace: str
    chat_models: dict[str, ChatModelClient]
    tool_gateway: ToolGateway
    max_retrieval_rounds: int = 3
    max_concurrent_subtasks: int = 3
    on_event: Any | None = None
    workspace_obj: Workspace | None = None
    task_store: TaskStore | None = None
    bus: Any | None = None  # research_agent.core.bus.Bus (lazy import to avoid cycles)
    # ADR-0046: optional Prior Knowledge retriever over the Knowledge Base;
    # None disables injection.
    local_retriever: Callable[[str], list[PriorKnowledgeChunk]] | None = None


class StateGraphRunner:
    """Orchestrates the full web research pipeline via LangGraph StateGraph."""

    def __init__(self, *, config: RunnerConfig) -> None:
        self.workspace = config.workspace_obj if config.workspace_obj is not None else Workspace(config.workspace)
        self.task_store = config.task_store if config.task_store is not None else TaskStore(self.workspace.root / "tasks.sqlite")
        self.chat_models = config.chat_models
        self.tool_gateway = config.tool_gateway
        self.max_retrieval_rounds = config.max_retrieval_rounds
        self.max_concurrent_subtasks = config.max_concurrent_subtasks
        self.on_event = config.on_event
        self._bus = config.bus
        self.local_retriever = config.local_retriever
        self._task_id: str | None = None
        self._event_seq: int = 0
        self._saved_source_ids: set[str] = set()
        self._llm_call_count: int = 0
        self.executor = ResearchExecutor(
            tool_gateway=config.tool_gateway,
            max_concurrent_subtasks=config.max_concurrent_subtasks,
            on_progress=lambda item: self._emit_progress_item(item),
        )

    # ── public API ──────────────────────────────────────────────────────

    def run(self, question: str, task_id: str | None = None) -> dict[str, Any]:
        self.workspace.ensure()
        task_id = task_id or generate_task_id()
        self._task_id = task_id
        created_at = utc_now_iso()
        state = create_initial_state(original_question=question)

        task_dir = self.workspace.task_dir(task_id)
        if not task_dir.exists():
            self.workspace.create_task_folder(
                task_id,
                task_metadata={"task_id": task_id, "mode": "web", "question": question, "created_at": created_at},
                result={"task_id": task_id, "mode": "web", "question": question, "status": "running", "created_at": created_at},
            )

        # ADR-0046: inject Prior Knowledge (local KB chunks) into the initial
        # state so the Planner can aim web research at genuine gaps. Retrieval
        # failure must never break Web Research — degrade to no injection.
        if self.local_retriever is not None:
            try:
                chunks = self.local_retriever(question) or []
            except Exception:
                logger.warning("Local retriever failed; continuing without prior knowledge", exc_info=True)
                chunks = []
            state["prior_knowledge"] = chunks
            if chunks:
                self._emit(
                    task_id,
                    "web_planning",
                    "progress",
                    f"Found {len(chunks)} relevant local notes.",
                    items=[{"kind": "source", "path": chunk.source_path, "title": chunk.source_path} for chunk in chunks],
                    event_subtype="source",
                )

        try:
            return self._run_graph(state, task_id, question, created_at)
        except Exception as exc:
            logger.exception("Web research failed")
            return self._persist_failed(task_id, question, created_at, ResearchError(
                code="runtime_error",
                message=str(exc),
            ))

    async def events(self):
        """Yield SSE frames via the bus, first replaying persisted events from file."""
        if self._task_id is None:
            raise RuntimeError("Cannot stream events: task_id is not set. Call run() first.")
        if self._bus is None:
            raise RuntimeError("Cannot stream events: bus is not configured.")

        bus = self._bus
        bus_channel = f"task.{self._task_id}"
        events_path = self.workspace.task_dir(self._task_id) / "events.jsonl"
        last_seq = -1

        # 1) Replay persisted events (catch-up).
        if events_path.exists():
            with open(events_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except Exception:
                        logger.warning("Failed to parse event line in %s: %s", events_path, line[:100])
                        continue
                    yield {"data": json.dumps(evt, ensure_ascii=False)}
                    last_seq = max(last_seq, evt.get("seq", -1))

        # 2) Live phase — subscribe to the bus, filtering by seq to skip
        #    events already replayed.
        async for payload in bus.subscribe(bus_channel):
            try:
                evt = json.loads(payload["data"])
            except Exception:
                continue
            if evt.get("seq", -1) <= last_seq:
                continue
            yield payload

    # ── graph execution ───────────────────────────────────────────────

    def _run_graph(self, state: WebResearchStateDict, task_id: str, question: str, created_at: str) -> dict[str, Any]:
        """Run the web research graph and handle post-graph persistence."""
        checkpointer_path = str(self.workspace.task_dir(task_id) / "checkpoints.sqlite")
        with SqliteSaver.from_conn_string(checkpointer_path) as checkpointer:
            graph_ctx = GraphContext(
                chat_models=self.chat_models,
                executor=self.executor,
                max_retrieval_rounds=self.max_retrieval_rounds,
                task_id=task_id,
                _emit=self._emit,
                _save_llm_call_artifact=self._save_llm_call_artifact,
                _save_source_snapshots=self._save_source_snapshots,
            )
            graph = build_web_research_graph(graph_ctx).compile(checkpointer=checkpointer)

            recursion_limit = (self.max_retrieval_rounds * 3) + 5
            config: dict[str, Any] = {
                "configurable": {"thread_id": task_id},
                "recursion_limit": recursion_limit,
            }

            try:
                final_state = graph.invoke(state, config)
            except GraphRecursionError:
                logger.warning("Web research hit recursion limit for task %s", task_id)
                return self._persist_failed(task_id, question, created_at, ResearchError(
                    code="runtime_error",
                    message="Web Research reached the retrieval limit without usable findings.",
                ))

            self._write_execution_trace(task_id, final_state)

            curator_output: CuratorOutput | None = final_state.get("curator_output")

            if curator_output is not None:
                try:
                    report_path = write_web_report(
                        workspace=self.workspace, task_id=task_id,
                        created_at=created_at, output=curator_output,
                    )
                except ResearchError as error:
                    self._emit(task_id, "web_curation", "failed", error.message)
                    return self._persist_failed(task_id, question, created_at, error)

                curate_items: list[dict[str, Any]] = []
                for s in curator_output.sources:
                    curate_items.append({"kind": "source", "title": s.title, "url": s.url})
                curate_items.append({"kind": "finding", "text": f"Report: {curator_output.title} — {curator_output.summary[:200]}"})
                if report_path:
                    curate_items.append({"kind": "source", "path": str(report_path)})
                self._emit(task_id, "web_curation", "completed", "Curation completed.", items=curate_items)

                result = {
                    "task_id": task_id, "mode": "web", "question": question,
                    "status": "completed", "created_at": created_at,
                    "completed_at": utc_now_iso(),
                    "curator_output": curator_output.to_dict(),
                    "report_path": str(report_path),
                }
                self._persist_result(task_id, question, created_at, result)
                self._emit(task_id, "web_curation", "task_result",
                           f"Task {result['status']}.",
                           items=[{"kind": "status", "task_id": task_id, "status": result["status"], "mode": "web"}])
                self._close_event_queue()
                return result
            else:
                return self._persist_failed(task_id, question, created_at, ResearchError(
                    code="runtime_error",
                    message="Web Research reached the retrieval limit without usable findings.",
                ))

    # ── persistence helpers ──────────────────────────────────────────

    def _persist_failed(self, task_id: str, question: str, created_at: str, error: ResearchError) -> dict[str, Any]:
        result = {
            "task_id": task_id, "mode": "web", "question": question,
            "status": "failed", "created_at": created_at,
            "completed_at": utc_now_iso(), "error": error.to_dict(),
        }
        self._persist_result(task_id, question, created_at, result)
        self._emit(task_id, "web_curation", "task_result", f"Task {result['status']}.",
                   items=[{"kind": "status", "task_id": task_id, "status": result["status"], "mode": "web"}])
        self._close_event_queue()
        return result

    def _persist_result(self, task_id: str, question: str, created_at: str, result: dict[str, Any]) -> None:
        result_path = self.workspace.task_dir(task_id) / "result.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.task_store.upsert_finished_task(TaskRecord(
            task_id=task_id, mode="web", status=result["status"],
            title_or_question=question, created_at=created_at,
            completed_at=result.get("completed_at"),
            report_path=result.get("report_path"), result_path=str(result_path),
        ))

    def _save_llm_call_artifact(self, task_id: str, role_name: str, prompt: str, output: dict[str, Any], *, round_num: int = 0, extra: dict[str, Any] | None = None) -> None:
        artifacts_dir = self.workspace.task_dir(task_id) / "artifacts" / "llm_calls"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        idx = self._llm_call_count
        self._llm_call_count += 1
        record = {"index": idx, "role": role_name, "round": round_num, "timestamp": utc_now_iso(), "prompt": prompt, "output": output}
        if extra:
            record["metadata"] = extra
        record_path = artifacts_dir / f"{idx:04d}_{role_name}_round{round_num:02d}.json"
        try:
            record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to save LLM call artifact: %s", exc)

    # ── execution trace (ADR-0013 V1.1) ──────────────────────────────

    def _write_execution_trace(self, task_id: str, final_state: WebResearchStateDict) -> None:
        route_history: list[str] = final_state.get("route_history", [])
        research_title: str = final_state.get("research_title", final_state["original_question"])
        retrieval_round: int = final_state.get("retrieval_round", 0)
        subtasks = final_state.get("subtasks", [])
        findings = final_state.get("findings", [])
        sources = final_state.get("sources", [])
        executor_outputs = final_state.get("executor_outputs", [])
        curator_output: CuratorOutput | None = final_state.get("curator_output")

        lines: list[str] = []
        lines.append(f"# Execution Trace: {research_title}")
        lines.append("")
        lines.append(f"**Question**: {final_state['original_question']}")
        lines.append(f"**Rounds**: {retrieval_round}")
        lines.append(f"**Subtasks**: {len(subtasks)} total ({_count_status(subtasks, 'completed')} completed, {_count_status(subtasks, 'failed')} failed, {_count_status(subtasks, 'skipped')} skipped)")
        lines.append(f"**Findings**: {len(findings)}")
        lines.append(f"**Sources**: {len(sources)}")
        lines.append(f"**Outcome**: {'curated' if curator_output is not None else 'failed'}")
        lines.append("")

        lines.extend(_render_mermaid_flowchart(route_history))

        lines.extend(_render_step_decisions(
            route_history, research_title, subtasks, executor_outputs,
            final_state, curator_output,
        ))

        trace_path = self.workspace.task_dir(task_id) / "execution_trace.md"
        try:
            trace_path.write_text("\n".join(lines), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to write execution_trace.md for %s: %s", task_id, exc)

    def _save_source_snapshots(self, task_id: str, state: WebResearchStateDict, new_sources: list[WebSource] | None = None) -> None:
        sources_dir = self.workspace.task_dir(task_id) / "artifacts" / "web_sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        sources_to_save = new_sources if new_sources is not None else state["sources"]
        for source in sources_to_save:
            if source.source_id in self._saved_source_ids:
                continue
            source_path = sources_dir / f"{source.source_id}.json"
            try:
                source_path.write_text(json.dumps(source.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
                self._saved_source_ids.add(source.source_id)
            except OSError as exc:
                logger.warning("Failed to save source snapshot %s: %s", source.source_id, exc)

    def _close_event_queue(self) -> None:
        """No-op: the Bus handles subscriber lifecycle automatically.

        Subscribers are unblocked when ``Bus.close()`` is called during
        server shutdown or when the subscriber disconnects and the
        ``async for`` loop exits (the queue is garbage-collected).
        """

    def _emit(self, task_id: str, phase: str, event_type: str, message: str, items: list[dict[str, Any]] | None = None, *, event_subtype: str | None = None) -> None:
        self._event_seq += 1
        event = ProgressEvent(
            task_id=task_id, mode="web", phase=phase, event_type=event_type,
            created_at=utc_now_iso(), message=message,
            details={"items": items or []}, seq=self._event_seq,
            event_subtype=event_subtype,
        )
        event_dict = event.to_dict()
        self.workspace.append_event(task_id, event_dict)
        if self._bus is not None:
            self._bus.publish_nowait(f"task.{task_id}", **event_dict)
        elif self.on_event is not None:
            # Fallback for CLI / tests: direct callback, no bus.
            self.on_event(event_dict)

    _PROGRESS_ITEM_MESSAGES: dict[str, str] = {
        "tool_call": "Tool call completed",
        "finding": "Finding discovered",
        "source": "Source captured",
        "subtask_started": "Subtask started",
        "subtask_completed": "Subtask completed",
        "subtask_failed": "Subtask failed",
    }

    def _emit_progress_item(self, item: dict[str, Any]) -> None:
        if self._task_id is None:
            return
        kind = item.get("kind", "progress")
        if kind not in _VALID_EVENT_SUBTYPES:
            logger.warning("Unknown progress item kind %r ignored by _emit_progress_item", kind)
            return
        message = self._PROGRESS_ITEM_MESSAGES.get(kind, kind)
        self._emit(self._task_id, "web_execution", "progress", message, items=[item], event_subtype=kind)
