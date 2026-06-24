from __future__ import annotations

from dataclasses import dataclass

from research_agent.web.schemas import ExecutorOutput, Finding, ResearchSubtask, WebResearchState, WebSource


@dataclass(frozen=True)
class PlannerInput:
    original_question: str
    current_plan: list[ResearchSubtask]
    executor_outputs: list[ExecutorOutput]
    research_gaps: list[str]
    plan_revision_request: str | None = None


@dataclass(frozen=True)
class ExecutorInput:
    original_question: str
    subtask: ResearchSubtask


@dataclass(frozen=True)
class SupervisorInput:
    original_question: str
    current_plan: list[ResearchSubtask]
    executor_outputs: list[ExecutorOutput]


@dataclass(frozen=True)
class CuratorInput:
    original_question: str
    title: str
    findings: list[Finding]
    sources: list[WebSource]


def build_planner_context(state: WebResearchState, plan_revision_request: str | None = None) -> PlannerInput:
    return PlannerInput(
        original_question=state.original_question,
        current_plan=list(state.subtasks),
        executor_outputs=list(state.executor_outputs),
        research_gaps=list(state.research_gaps),
        plan_revision_request=plan_revision_request,
    )


def build_executor_context(state: WebResearchState, subtask_id: str) -> ExecutorInput:
    subtask = next(subtask for subtask in state.subtasks if subtask.subtask_id == subtask_id)
    return ExecutorInput(original_question=state.original_question, subtask=subtask)


def build_supervisor_context(state: WebResearchState) -> SupervisorInput:
    return SupervisorInput(
        original_question=state.original_question,
        current_plan=list(state.subtasks),
        executor_outputs=list(state.executor_outputs),
    )


def build_curator_context(state: WebResearchState) -> CuratorInput:
    return CuratorInput(
        original_question=state.original_question,
        title=state.research_title or state.original_question,
        findings=list(state.findings),
        sources=list(state.sources),
    )
