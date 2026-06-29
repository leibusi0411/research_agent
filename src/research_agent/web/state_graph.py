from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from research_agent.core.errors import ResearchError
from research_agent.core.ids import generate_task_id, utc_now_iso
from research_agent.core.providers import ChatModelClient
from research_agent.core.tasks import TaskRecord, TaskStore
from research_agent.core.workspace import Workspace
from research_agent.web.prompt_builders import (
    build_curator_prompt,
    build_executor_tool_plan_prompt,
    build_executor_synthesis_prompt,
    build_planner_prompt,
    build_supervisor_prompt,
)
from research_agent.web.report import write_web_report
from research_agent.web.role_invocation import invoke_role_json
from research_agent.web.schemas import (
    CuratorOutput,
    ExecutorOutput,
    Finding,
    PlannerOutput,
    PlannerSubtaskDraft,
    ProgressEvent,
    ResearchSubtask,
    SupervisorOutput,
    WebResearchState,
    WebSource,
)
from research_agent.web.tools import ToolGateway

logger = logging.getLogger(__name__)


def _validate_planner_payload(payload: dict[str, Any]) -> dict[str, Any]:
    title = payload.get("research_title")
    subtasks = payload.get("subtasks")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("research_title must be a non-empty string")
    if not isinstance(subtasks, list) or not subtasks:
        raise ValueError("subtasks must be a non-empty list")
    for subtask in subtasks:
        if not isinstance(subtask, dict) or not isinstance(subtask.get("question"), str) or not subtask["question"].strip():
            raise ValueError("each subtask must include a non-empty question")
    return payload


def _validate_executor_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload.get("subtask_id"), str):
        raise ValueError("subtask_id must be a string")
    if payload.get("status") not in ("completed", "failed"):
        raise ValueError("status must be 'completed' or 'failed'")
    if not isinstance(payload.get("findings"), list):
        raise ValueError("findings must be a list")
    if not isinstance(payload.get("sources"), list):
        raise ValueError("sources must be a list")
    return payload


def _validate_tool_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload.get("tool_calls"), list):
        raise ValueError("tool_calls must be a list")
    for tc in payload["tool_calls"]:
        if not isinstance(tc.get("name"), str):
            raise ValueError("each tool_call must have a 'name' string")
        if not isinstance(tc.get("arguments"), dict):
            raise ValueError("each tool_call must have an 'arguments' object")
    return payload


def _validate_synthesis_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload.get("findings"), list):
        raise ValueError("findings must be a list")
    if not isinstance(payload.get("sources"), list):
        raise ValueError("sources must be a list")
    return payload


def _validate_supervisor_payload(payload: dict[str, Any]) -> dict[str, Any]:
    valid_routes = {"continue_execution", "revise_plan", "curate", "fail"}
    if payload.get("route") not in valid_routes:
        raise ValueError(f"route must be one of {valid_routes}")
    if not isinstance(payload.get("reason"), str) or not payload["reason"].strip():
        raise ValueError("reason must be a non-empty string")
    return payload


def _validate_curator_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload.get("title"), str) or not payload["title"].strip():
        raise ValueError("title must be a non-empty string")
    if not isinstance(payload.get("summary"), str) or not payload["summary"].strip():
        raise ValueError("summary must be a non-empty string")
    return payload


def _parse_executor_output(payload: dict[str, Any], subtask_id: str) -> ExecutorOutput:
    findings = []
    for f in payload.get("findings", []):
        findings.append(Finding(
            finding_id=f.get("finding_id", f"f_{subtask_id}"),
            subtask_id=f.get("subtask_id", subtask_id),
            text=f.get("text", ""),
            source_ids=f.get("source_ids", []),
        ))

    sources = []
    for s in payload.get("sources", []):
        sources.append(WebSource(
            source_id=s.get("source_id", f"src_{subtask_id}"),
            title=s.get("title", ""),
            url=s.get("url", ""),
            fetched_at=s.get("fetched_at", utc_now_iso()),
        ))

    return ExecutorOutput(
        subtask_id=subtask_id,
        status=payload.get("status", "completed"),
        findings=findings,
        sources=sources,
        failure_reason=payload.get("failure_reason"),
    )


def _parse_supervisor_output(payload: dict[str, Any]) -> SupervisorOutput:
    return SupervisorOutput(
        route=payload["route"],
        reason=payload["reason"],
        next_subtask_ids=payload.get("next_subtask_ids", []),
        skip_subtask_ids=payload.get("skip_subtask_ids", []),
        plan_revision_request=payload.get("plan_revision_request"),
        research_gaps=payload.get("research_gaps", []),
        saturation=payload.get("saturation", False),
    )


def _parse_curator_output(payload: dict[str, Any]) -> CuratorOutput:
    findings = []
    for f in payload.get("findings", []):
        findings.append(Finding(
            finding_id=f.get("finding_id", ""),
            subtask_id=f.get("subtask_id", ""),
            text=f.get("text", ""),
            source_ids=f.get("source_ids", []),
        ))

    sources = []
    for s in payload.get("sources", []):
        sources.append(WebSource(
            source_id=s.get("source_id", ""),
            title=s.get("title", ""),
            url=s.get("url", ""),
            fetched_at=s.get("fetched_at", ""),
        ))

    return CuratorOutput(
        title=payload["title"],
        summary=payload["summary"],
        findings=findings,
        sources=sources,
    )


class ResearchExecutor:
    def __init__(
        self,
        *,
        tool_gateway: ToolGateway,
        max_concurrent_subtasks: int = 3,
    ) -> None:
        self.tool_gateway = tool_gateway
        self.max_concurrent_subtasks = max_concurrent_subtasks

    def execute(
        self,
        state: WebResearchState,
        subtask_ids: list[str],
        chat_model: ChatModelClient,
    ) -> list[ExecutorOutput]:
        if not subtask_ids:
            return []

        outputs: list[ExecutorOutput] = []
        with ThreadPoolExecutor(max_workers=self.max_concurrent_subtasks) as executor:
            futures = {
                executor.submit(self._execute_single, state, subtask_id, chat_model): subtask_id
                for subtask_id in subtask_ids
            }
            for future in as_completed(futures):
                subtask_id = futures[future]
                try:
                    output = future.result()
                    outputs.append(output)
                except Exception as exc:
                    logger.exception("Subtask %s failed", subtask_id)
                    outputs.append(ExecutorOutput(
                        subtask_id=subtask_id,
                        status="failed",
                        findings=[],
                        sources=[],
                        failure_reason=str(exc),
                    ))

        return outputs

    def _execute_single(
        self,
        state: WebResearchState,
        subtask_id: str,
        chat_model: ChatModelClient,
    ) -> ExecutorOutput:
        try:
            return self._execute_with_tools(state, subtask_id, chat_model)
        except ResearchError as exc:
            return ExecutorOutput(
                subtask_id=subtask_id,
                status="failed",
                findings=[],
                sources=[],
                failure_reason=exc.message,
            )

    def _execute_with_tools(
        self,
        state: WebResearchState,
        subtask_id: str,
        chat_model: ChatModelClient,
    ) -> ExecutorOutput:
        # Step 1: Ask LLM to plan tool calls
        tool_plan_prompt = build_executor_tool_plan_prompt(state, subtask_id)
        tool_plan_schema = json.dumps({
            "tool_calls": [{"name": "string", "arguments": {}}],
        })
        tool_plan = invoke_role_json(
            role_name="executor",
            prompt=tool_plan_prompt,
            target_schema=tool_plan_schema,
            chat_model=chat_model,
            validator=_validate_tool_plan_payload,
        )

        # Step 2: Execute tool calls and collect results
        tool_results: list[dict[str, Any]] = []
        for tc in tool_plan.get("tool_calls", []):
            result = self.tool_gateway.call("web_research", tc)
            tool_results.append({
                "tool": tc.get("name", "unknown"),
                "arguments": tc.get("arguments", {}),
                "status": result.status,
                "data": result.data,
                "error": result.error,
                "message": result.message,
            })

        # Guard: if LLM returned no tool calls, fail early — don't hallucinate from nothing
        if not tool_results:
            return ExecutorOutput(
                subtask_id=subtask_id,
                status="failed",
                findings=[],
                sources=[],
                failure_reason="Executor LLM returned no tool calls for this subtask.",
            )

        # Step 3: Ask LLM to synthesize findings from tool results
        synthesis_prompt = build_executor_synthesis_prompt(state, subtask_id, tool_results)
        synthesis_schema = json.dumps({
            "subtask_id": "string",
            "status": "completed|failed",
            "findings": [{"finding_id": "string", "subtask_id": "string", "text": "string", "source_ids": ["string"]}],
            "sources": [{"source_id": "string", "title": "string", "url": "string", "fetched_at": "string"}],
            "failure_reason": "string|null",
        })
        payload = invoke_role_json(
            role_name="executor",
            prompt=synthesis_prompt,
            target_schema=synthesis_schema,
            chat_model=chat_model,
            validator=_validate_executor_payload,
        )
        return _parse_executor_output(payload, subtask_id)


class StateGraphRunner:
    def __init__(
        self,
        *,
        workspace: str,
        chat_models: dict[str, ChatModelClient],
        tool_gateway: ToolGateway,
        max_retrieval_rounds: int = 3,
        max_concurrent_subtasks: int = 3,
        on_event: Any | None = None,
    ) -> None:
        self.workspace = Workspace(workspace)
        self.task_store = TaskStore(self.workspace.root / "tasks.sqlite")
        self.chat_models = chat_models
        self.tool_gateway = tool_gateway
        self.max_retrieval_rounds = max_retrieval_rounds
        self.max_concurrent_subtasks = max_concurrent_subtasks
        self.on_event = on_event
        self.executor = ResearchExecutor(
            tool_gateway=tool_gateway,
            max_concurrent_subtasks=max_concurrent_subtasks,
        )

    def run(self, question: str, task_id: str | None = None) -> dict[str, Any]:
        self.workspace.ensure()
        task_id = task_id or generate_task_id()
        created_at = utc_now_iso()
        state = WebResearchState(original_question=question)

        task_dir = self.workspace.task_dir(task_id)
        if not task_dir.exists():
            self.workspace.create_task_folder(
                task_id,
                task_metadata={"task_id": task_id, "mode": "web", "question": question, "created_at": created_at},
                result={"task_id": task_id, "mode": "web", "question": question, "status": "running", "created_at": created_at},
            )

        try:
            return self._run_graph(state, task_id, question, created_at)
        except Exception as exc:
            logger.exception("Web research failed")
            return self._persist_failed(task_id, question, created_at, ResearchError(
                code="runtime_error",
                message=str(exc),
            ))

    def _run_graph(self, state: WebResearchState, task_id: str, question: str, created_at: str) -> dict[str, Any]:
        # Step 1: Plan
        self._emit(task_id, "web_planning", "started", "Planning web research.")
        planner_payload = invoke_role_json(
            role_name="planner",
            prompt=build_planner_prompt(state),
            target_schema='{"research_title": "string", "subtasks": [{"question": "string"}]}',
            chat_model=self.chat_models["planner"],
            validator=_validate_planner_payload,
        )
        planner_output = PlannerOutput(
            research_title=planner_payload["research_title"],
            subtasks=[PlannerSubtaskDraft(question=s["question"]) for s in planner_payload["subtasks"]],
        )
        state.add_planner_output(planner_output)
        self._emit(task_id, "web_planning", "completed", f"Plan created with {len(planner_output.subtasks)} subtasks.")

        # Step 2: Execute -> Supervise loop
        _next_target_ids: list[str] | None = None
        while True:
            pending_ids = [s.subtask_id for s in state.subtasks if s.status == "pending"]
            if not pending_ids:
                break

            # Honor supervisor's next_subtask_ids when provided
            if _next_target_ids is not None:
                pending_ids = [sid for sid in pending_ids if sid in _next_target_ids]
                _next_target_ids = None

            if not pending_ids:
                break

            self._emit(task_id, "web_execution", "started", f"Executing {len(pending_ids)} subtasks.")
            executor_outputs = self.executor.execute(state, pending_ids, self.chat_models["executor"])
            for output in executor_outputs:
                state.merge_executor_output(output)
            state.retrieval_round += 1
            self._emit(task_id, "web_execution", "completed", "Subtasks executed.")

            # Save blackboard snapshot
            self._save_blackboard_snapshot(task_id, state)

            # Save source snapshots
            self._save_source_snapshots(task_id, state)

            # Supervise
            self._emit(task_id, "web_supervision", "started", "Evaluating research progress.")
            supervisor_payload = invoke_role_json(
                role_name="supervisor",
                prompt=build_supervisor_prompt(state),
                target_schema='{"route": "string", "reason": "string", "next_subtask_ids": ["string"], "skip_subtask_ids": ["string"], "plan_revision_request": "string|null", "research_gaps": ["string"], "saturation": false}',
                chat_model=self.chat_models["supervisor"],
                validator=_validate_supervisor_payload,
            )
            supervisor_output = _parse_supervisor_output(supervisor_payload)
            state.apply_supervisor_output(supervisor_output)
            self._emit(task_id, "web_supervision", "completed", supervisor_output.reason)

            # Route guard
            route = self._guard_route(state, supervisor_output.route)

            if route == "continue_execution":
                # Guard: "continue" with nothing to continue → redirect to termination
                if not supervisor_output.next_subtask_ids:
                    route = "curate" if state.findings and state.sources else "fail"
                    state.route_history.append(route)
                    # Fall through to curate/fail below
                else:
                    _next_target_ids = supervisor_output.next_subtask_ids
                    continue
            elif route == "revise_plan":
                # Note: _next_target_ids already consumed above — new subtasks
                # from re-plan will execute unfiltered next iteration.
                # Re-plan
                self._emit(task_id, "web_revision", "started", "Revising plan.")
                revision_payload = invoke_role_json(
                    role_name="planner",
                    prompt=build_planner_prompt(state, revision=True),
                    target_schema='{"research_title": "string", "subtasks": [{"question": "string"}]}',
                    chat_model=self.chat_models["planner"],
                    validator=_validate_planner_payload,
                )
                revision_output = PlannerOutput(
                    research_title=revision_payload["research_title"],
                    subtasks=[PlannerSubtaskDraft(question=s["question"]) for s in revision_payload["subtasks"]],
                )
                state.add_planner_output(revision_output)
                self._emit(task_id, "web_revision", "completed", f"Plan revised with {len(revision_output.subtasks)} new subtasks.")
                continue
            elif route == "curate":
                return self._curate(state, task_id, question, created_at)
            else:  # fail
                return self._fail(state, task_id, question, created_at)

        # If we exit the loop without curating, try to curate anyway
        if state.findings and state.sources:
            return self._curate(state, task_id, question, created_at)
        return self._fail(state, task_id, question, created_at)

    def _guard_route(self, state: WebResearchState, route: str) -> str:
        # At retrieval limit, force termination: both continue_execution and revise_plan
        # must redirect to curate (if usable findings exist) or fail.
        if state.retrieval_round >= self.max_retrieval_rounds:
            if route in ("continue_execution", "revise_plan"):
                guarded = "curate" if state.findings and state.sources else "fail"
                state.route_history.append(guarded)
                return guarded
        state.route_history.append(route)
        return route

    def _curate(self, state: WebResearchState, task_id: str, question: str, created_at: str) -> dict[str, Any]:
        self._emit(task_id, "web_curation", "started", "Curating findings.")
        curator_payload = invoke_role_json(
            role_name="curator",
            prompt=build_curator_prompt(state),
            target_schema='{"title": "string", "summary": "string", "findings": [], "sources": []}',
            chat_model=self.chat_models["curator"],
            validator=_validate_curator_payload,
        )
        curator_output = _parse_curator_output(curator_payload)
        state.curator_output = curator_output

        try:
            report_path = write_web_report(
                workspace=self.workspace,
                task_id=task_id,
                created_at=created_at,
                output=curator_output,
            )
        except ResearchError as error:
            self._emit(task_id, "web_curation", "failed", error.message)
            return self._persist_failed(task_id, question, created_at, error)

        self._emit(task_id, "web_curation", "completed", "Curation completed.")

        result = {
            "task_id": task_id,
            "mode": "web",
            "question": question,
            "status": "completed",
            "created_at": created_at,
            "completed_at": utc_now_iso(),
            "curator_output": curator_output.to_dict(),
            "report_path": str(report_path),
        }

        self._persist_result(task_id, question, created_at, result)
        return result

    def _fail(self, state: WebResearchState, task_id: str, question: str, created_at: str) -> dict[str, Any]:
        error = ResearchError(code="runtime_error", message="Web Research reached the retrieval limit without usable findings.")
        return self._persist_failed(task_id, question, created_at, error)

    def _persist_failed(self, task_id: str, question: str, created_at: str, error: ResearchError) -> dict[str, Any]:
        result = {
            "task_id": task_id,
            "mode": "web",
            "question": question,
            "status": "failed",
            "created_at": created_at,
            "completed_at": utc_now_iso(),
            "error": error.to_dict(),
        }
        self._persist_result(task_id, question, created_at, result)
        return result

    def _persist_result(self, task_id: str, question: str, created_at: str, result: dict[str, Any]) -> None:
        result_path = self.workspace.task_dir(task_id) / "result.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.task_store.upsert_finished_task(
            TaskRecord(
                task_id=task_id,
                mode="web",
                status=result["status"],
                title_or_question=question,
                created_at=created_at,
                completed_at=result.get("completed_at"),
                report_path=result.get("report_path"),
                result_path=str(result_path),
            )
        )

    def _save_blackboard_snapshot(self, task_id: str, state: WebResearchState) -> None:
        snapshot = {
            "original_question": state.original_question,
            "research_title": state.research_title,
            "subtasks": [
                {"subtask_id": s.subtask_id, "question": s.question, "status": s.status}
                for s in state.subtasks
            ],
            "findings": [f.to_dict() for f in state.findings],
            "sources": [s.to_dict() for s in state.sources],
            "research_gaps": state.research_gaps,
            "retrieval_round": state.retrieval_round,
            "route_history": state.route_history,
        }
        snapshot_path = self.workspace.task_dir(task_id) / "blackboard_snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    def _save_source_snapshots(self, task_id: str, state: WebResearchState) -> None:
        sources_dir = self.workspace.task_dir(task_id) / "artifacts" / "web_sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        for source in state.sources:
            source_path = sources_dir / f"{source.source_id}.json"
            source_path.write_text(json.dumps(source.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _emit(self, task_id: str, phase: str, event_type: str, message: str) -> None:
        event = ProgressEvent(
            task_id=task_id,
            mode="web",
            phase=phase,
            event_type=event_type,
            created_at=utc_now_iso(),
            message=message,
            details={"items": []},
        )
        event_dict = event.to_dict()
        self.workspace.append_event(task_id, event_dict)
        if self.on_event is not None:
            self.on_event(event_dict)