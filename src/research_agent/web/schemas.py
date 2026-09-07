from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict


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


@dataclass(frozen=True)
class ResearchSubtask:
    subtask_id: str
    question: str
    status: SubtaskStatus = "pending"


@dataclass(frozen=True)
class PriorKnowledgeChunk:
    """A Knowledge Base chunk injected into the Planner as Prior Knowledge (ADR-0046)."""

    text: str
    source_path: str
    heading_path: list[str]


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
    seq: int = 0  # R-112: public field name — consumers use this for dedup
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
            "seq": self.seq,
            "details": self.details,
        }


# ── LangGraph-compatible TypedDict state ────────────────────────────────────


def _merge_subtasks(
    left: list[ResearchSubtask], right: list[ResearchSubtask]
) -> list[ResearchSubtask]:
    """Merge subtask lists: update existing by subtask_id, append new ones.

    Used as an ``Annotated`` reducer in ``WebResearchStateDict`` so that
    nodes returning partial subtask lists (e.g. status updates after
    execution or skip markings after supervision) correctly merge into
    the existing list rather than replacing it.
    """
    right_by_id = {st.subtask_id: st for st in right}
    result: list[ResearchSubtask] = []
    seen: set[str] = set()
    for st in left:
        result.append(right_by_id.get(st.subtask_id, st))
        seen.add(st.subtask_id)
    for st in right:
        if st.subtask_id not in seen:
            result.append(st)
    return result


class WebResearchStateDict(TypedDict, total=False):
    """LangGraph-compatible TypedDict state with ``Annotated`` reducers.

    Replaces the mutable ``WebResearchState`` dataclass for the LangGraph
    migration (ADR-0013 V1.1).  List fields use ``operator.add`` (append)
    or the custom ``_merge_subtasks`` reducer; scalar fields use
    last-write-wins (the LangGraph default).

    ``total=False`` allows nodes to return partial state updates.
    """

    original_question: str
    research_title: str | None
    prior_knowledge: list[PriorKnowledgeChunk]
    subtasks: Annotated[list[ResearchSubtask], _merge_subtasks]
    executor_outputs: Annotated[list[ExecutorOutput], operator.add]
    findings: Annotated[list[Finding], operator.add]
    sources: Annotated[list[WebSource], operator.add]
    research_gaps: list[str]
    last_supervisor_output: SupervisorOutput | None
    curator_output: CuratorOutput | None
    route_history: Annotated[list[str], operator.add]
    revision_subtask_ids: Annotated[list[str], operator.add]  # R-123: track IDs added by plan_revision
    retrieval_round: int


def check_required_field(payload: dict[str, Any], field: str, expected_type: type, *, allow_empty: bool = False) -> None:
    """Validate that *payload* has *field* as *expected_type*, raising ``ValueError``.

    Shared between graph.py and executor.py validators to reduce isinstance
    boilerplate (R-113).
    """
    value = payload.get(field)
    if not isinstance(value, expected_type):
        raise ValueError(f"{field} must be a {expected_type.__name__}")
    if not allow_empty and isinstance(value, str) and not value.strip():
        raise ValueError(f"{field} must be non-empty")


def create_initial_state(
    original_question: str,
    *,
    prior_knowledge: list[PriorKnowledgeChunk] | None = None,
) -> WebResearchStateDict:
    """Return a fresh ``WebResearchStateDict`` with all fields initialized."""
    return {
        "original_question": original_question,
        "research_title": None,
        "prior_knowledge": list(prior_knowledge or []),
        "subtasks": [],
        "executor_outputs": [],
        "findings": [],
        "sources": [],
        "research_gaps": [],
        "last_supervisor_output": None,
        "curator_output": None,
        "route_history": [],
        "revision_subtask_ids": [],
        "retrieval_round": 0,
    }
