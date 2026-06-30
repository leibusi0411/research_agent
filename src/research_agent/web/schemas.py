from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


SubtaskStatus = Literal["pending", "completed", "failed", "skipped"]
ExecutorStatus = Literal["completed", "failed"]
SupervisorRoute = Literal["continue_execution", "revise_plan", "curate", "fail"]
ProgressMode = Literal["local", "web"]
ProgressPhase = Literal["local_rag", "web_planning", "web_execution", "web_supervision", "web_revision", "web_curation"]
ProgressEventType = Literal["started", "progress", "completed", "failed", "task_result"]


@dataclass(frozen=True)
class PlannerSubtaskDraft:
    question: str


@dataclass(frozen=True)
class PlannerOutput:
    research_title: str
    subtasks: list[PlannerSubtaskDraft]


@dataclass
class ResearchSubtask:
    subtask_id: str
    question: str
    status: SubtaskStatus = "pending"


@dataclass(frozen=True)
class WebSource:
    source_id: str
    title: str
    url: str
    fetched_at: str

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "fetched_at": self.fetched_at,
        }


@dataclass(frozen=True)
class Finding:
    finding_id: str
    subtask_id: str
    text: str
    source_ids: list[str]

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "subtask_id": self.subtask_id,
            "text": self.text,
            "source_ids": self.source_ids,
        }


@dataclass(frozen=True)
class ExecutorOutput:
    subtask_id: str
    status: ExecutorStatus
    findings: list[Finding]
    sources: list[WebSource]
    failure_reason: str | None = None


@dataclass(frozen=True)
class SupervisorOutput:
    route: SupervisorRoute
    reason: str
    next_subtask_ids: list[str]
    skip_subtask_ids: list[str]
    plan_revision_request: str | None
    research_gaps: list[str]
    saturation: bool


@dataclass(frozen=True)
class CuratorOutput:
    title: str
    summary: str
    findings: list[Finding]
    sources: list[WebSource]

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "summary": self.summary,
            "findings": [finding.to_dict() for finding in self.findings],
            "sources": [source.to_dict() for source in self.sources],
        }


@dataclass(frozen=True)
class ProgressEvent:
    task_id: str
    mode: ProgressMode
    phase: ProgressPhase
    event_type: ProgressEventType
    created_at: str
    message: str
    details: dict
    _seq: int = 0
    event_subtype: str | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "mode": self.mode,
            "phase": self.phase,
            "event_type": self.event_type,
            "event_subtype": self.event_subtype,
            "created_at": self.created_at,
            "message": self.message,
            "_seq": self._seq,
            "details": self.details,
        }


@dataclass
class WebResearchState:
    original_question: str
    research_title: str | None = None
    subtasks: list[ResearchSubtask] = field(default_factory=list)
    executor_outputs: list[ExecutorOutput] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    sources: list[WebSource] = field(default_factory=list)
    research_gaps: list[str] = field(default_factory=list)
    last_supervisor_output: SupervisorOutput | None = None
    curator_output: CuratorOutput | None = None
    route_history: list[str] = field(default_factory=list)
    retrieval_round: int = 0

    def add_planner_output(self, output: PlannerOutput) -> None:
        self.research_title = output.research_title
        next_id = len(self.subtasks) + 1
        for index, draft in enumerate(output.subtasks, start=next_id):
            self.subtasks.append(ResearchSubtask(subtask_id=f"st_{index}", question=draft.question))

    def merge_executor_output(self, output: ExecutorOutput) -> None:
        self.executor_outputs.append(output)
        for subtask in self.subtasks:
            if subtask.subtask_id == output.subtask_id:
                subtask.status = output.status
                break
        self.findings.extend(output.findings)
        self.sources.extend(output.sources)

    def apply_supervisor_output(self, output: SupervisorOutput) -> None:
        self.last_supervisor_output = output
        self.research_gaps = output.research_gaps
        for subtask in self.subtasks:
            if subtask.subtask_id in output.skip_subtask_ids and subtask.status == "pending":
                subtask.status = "skipped"
