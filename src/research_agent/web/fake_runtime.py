from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from research_agent.core.errors import ResearchError
from research_agent.core.ids import generate_task_id, utc_now_iso
from research_agent.core.tasks import TaskRecord, TaskStore
from research_agent.core.workspace import Workspace
from research_agent.web.context import build_curator_context
from research_agent.web.report import write_web_report
from research_agent.web.schemas import (
    CuratorOutput,
    ExecutorOutput,
    Finding,
    PlannerOutput,
    PlannerSubtaskDraft,
    SupervisorOutput,
    WebResearchState,
    WebSource,
    ProgressEvent,
)


class FakeWebResearchRuntime:
    def __init__(
        self,
        workspace: str | Path,
        *,
        max_retrieval_rounds: int = 3,
        produce_findings: bool = True,
        first_supervisor_route: str | None = None,
        fail_report_write: bool = False,
        schema_failure: bool = False,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        event_delay_seconds: float = 0,
    ) -> None:
        self.workspace = Workspace(workspace)
        self.task_store = TaskStore(self.workspace.root / "tasks.sqlite")
        self.max_retrieval_rounds = max_retrieval_rounds
        self.produce_findings = produce_findings
        self.first_supervisor_route = first_supervisor_route
        self.fail_report_write = fail_report_write
        self.schema_failure = schema_failure
        self.on_event = on_event
        self.event_delay_seconds = event_delay_seconds

    def run(self, question: str, task_id: str | None = None) -> dict[str, Any]:
        self.workspace.ensure()
        task_id = task_id or generate_task_id()
        created_at = utc_now_iso()
        if self.schema_failure:
            error = ResearchError(code="schema_validation_failed", message="Failed to repair Web Research schema output.")
            result = {
                "task_id": task_id,
                "mode": "web",
                "question": question,
                "status": "failed",
                "created_at": created_at,
                "completed_at": utc_now_iso(),
                "error": error.to_dict(),
            }
            self.workspace.create_task_folder(
                task_id,
                task_metadata={"task_id": task_id, "mode": "web", "question": question, "created_at": created_at},
                result=result,
            )
            result_path = self.workspace.task_dir(task_id) / "result.json"
            self.task_store.upsert_finished_task(
                TaskRecord(
                    task_id=task_id,
                    mode="web",
                    status="failed",
                    title_or_question=question,
                    created_at=created_at,
                    completed_at=result["completed_at"],
                    report_path=None,
                    result_path=str(result_path),
                )
            )
            return result
        state = WebResearchState(original_question=question)
        self.workspace.create_task_folder(
            task_id,
            task_metadata={"task_id": task_id, "mode": "web", "question": question, "created_at": created_at},
            result={"task_id": task_id, "mode": "web", "question": question, "status": "running"},
        )

        self._emit(task_id, "web_planning", "started", "Planning web research.")
        state.add_planner_output(self._plan(question, revision=False))
        self._emit(task_id, "web_planning", "completed", "Initial plan created.")

        pending_ids = [subtask.subtask_id for subtask in state.subtasks if subtask.status == "pending"]
        self._execute(state, task_id, pending_ids[:1])

        supervisor_output = self._supervise_after_first_execution()
        state.apply_supervisor_output(supervisor_output)
        self._emit(task_id, "web_supervision", "completed", supervisor_output.reason)

        route = self._guard_route(state, supervisor_output.route)
        if route == "continue_execution":
            self._execute(state, task_id, supervisor_output.next_subtask_ids)
            final_supervisor = SupervisorOutput(
                route="curate",
                reason="Continued execution completed.",
                next_subtask_ids=[],
                skip_subtask_ids=[],
                plan_revision_request=None,
                research_gaps=state.research_gaps,
                saturation=True,
            )
            state.apply_supervisor_output(final_supervisor)
            self._emit(task_id, "web_supervision", "completed", final_supervisor.reason)
            route = self._guard_route(state, final_supervisor.route)

        if route == "revise_plan":
            self._emit(task_id, "web_revision", "started", "Revising plan.")
            state.add_planner_output(self._plan(question, revision=True))
            self._emit(task_id, "web_revision", "completed", "Plan revision appended subtasks.")
            pending_ids = [subtask.subtask_id for subtask in state.subtasks if subtask.status == "pending"]
            self._execute(state, task_id, pending_ids)
            final_supervisor = SupervisorOutput(
                route="curate",
                reason="Research saturation reached.",
                next_subtask_ids=[],
                skip_subtask_ids=[],
                plan_revision_request=None,
                research_gaps=state.research_gaps,
                saturation=True,
            )
            state.apply_supervisor_output(final_supervisor)
            self._emit(task_id, "web_supervision", "completed", final_supervisor.reason)
            route = self._guard_route(state, final_supervisor.route)

        if route == "curate":
            result = self._curate(state, task_id, question, created_at)
        else:
            result = self._fail(state, task_id, question, created_at)

        serializable = {key: value for key, value in result.items() if key != "state"}
        result_path = self.workspace.task_dir(task_id) / "result.json"
        result_path.write_text(
            json.dumps(serializable, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
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
        return result

    def _plan(self, question: str, *, revision: bool) -> PlannerOutput:
        if revision:
            return PlannerOutput(question, [PlannerSubtaskDraft("Find implementation examples.")])
        return PlannerOutput(
            question,
            [
                PlannerSubtaskDraft("Find architecture overview."),
                PlannerSubtaskDraft("Find outdated direction to skip."),
            ],
        )

    def _execute(self, state: WebResearchState, task_id: str, subtask_ids: list[str]) -> None:
        if not subtask_ids:
            return
        self._emit(task_id, "web_execution", "started", "Executing subtasks.")
        for subtask_id in subtask_ids:
            if not self.produce_findings:
                output = ExecutorOutput(subtask_id=subtask_id, status="failed", findings=[], sources=[], failure_reason="No sources.")
            else:
                source_number = len(state.sources) + 1
                finding_number = len(state.findings) + 1
                source = WebSource(
                    source_id=f"src_{source_number}",
                    title=f"Source {source_number}",
                    url=f"https://example.com/source-{source_number}",
                    fetched_at=utc_now_iso(),
                )
                finding = Finding(
                    finding_id=f"f_{finding_number}",
                    subtask_id=subtask_id,
                    text=f"Finding for {subtask_id}.",
                    source_ids=[source.source_id],
                )
                output = ExecutorOutput(subtask_id=subtask_id, status="completed", findings=[finding], sources=[source])
            state.merge_executor_output(output)
        state.retrieval_round += 1
        self._emit(task_id, "web_execution", "completed", "Subtasks executed.")

    def _supervise_after_first_execution(self) -> SupervisorOutput:
        route = self.first_supervisor_route or ("continue_execution" if self.max_retrieval_rounds == 0 else "revise_plan")
        return SupervisorOutput(
            route=route,
            reason="Need implementation examples.",
            next_subtask_ids=["st_2"] if route == "continue_execution" else [],
            skip_subtask_ids=["st_2"],
            plan_revision_request="Add implementation examples.",
            research_gaps=["Need implementation examples."],
            saturation=False,
        )

    def _guard_route(self, state: WebResearchState, route: str) -> str:
        if route == "continue_execution" and state.retrieval_round >= self.max_retrieval_rounds:
            guarded = "curate" if state.findings and state.sources else "fail"
            state.route_history.append(guarded)
            return guarded
        state.route_history.append(route)
        return route

    def _curate(self, state: WebResearchState, task_id: str, question: str, created_at: str) -> dict[str, Any]:
        self._emit(task_id, "web_curation", "started", "Curating findings.")
        context = build_curator_context(state)
        state.curator_output = CuratorOutput(
            title=context.title,
            summary=f"Summary for {question}.",
            findings=context.findings,
            sources=context.sources,
        )
        try:
            if self.fail_report_write:
                raise ResearchError(code="file_write_error", message="Failed to write Web Report File: simulated failure")
            report_path = write_web_report(
                workspace=self.workspace,
                task_id=task_id,
                created_at=created_at,
                output=state.curator_output,
            )
        except ResearchError as error:
            self._emit(task_id, "web_curation", "failed", error.message)
            return {
                "task_id": task_id,
                "mode": "web",
                "question": question,
                "status": "failed",
                "created_at": created_at,
                "completed_at": utc_now_iso(),
                "error": error.to_dict(),
                "state": state,
            }
        self._emit(task_id, "web_curation", "completed", "Curation completed.")
        return {
            "task_id": task_id,
            "mode": "web",
            "question": question,
            "status": "completed",
            "created_at": created_at,
            "completed_at": utc_now_iso(),
            "curator_output": state.curator_output.to_dict(),
            "report_path": str(report_path),
            "state": state,
        }

    def _fail(self, state: WebResearchState, task_id: str, question: str, created_at: str) -> dict[str, Any]:
        error = ResearchError(code="runtime_error", message="Web Research reached the retrieval limit without usable findings.")
        return {
            "task_id": task_id,
            "mode": "web",
            "question": question,
            "status": "failed",
            "created_at": created_at,
            "completed_at": utc_now_iso(),
            "error": error.to_dict(),
            "state": state,
        }

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
        if self.event_delay_seconds > 0:
            time.sleep(self.event_delay_seconds)
