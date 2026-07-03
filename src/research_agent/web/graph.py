from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from research_agent.core.providers import ChatModelClient
from research_agent.web.executor import ResearchExecutor
from research_agent.web.prompt_builders import (
    build_curator_prompt,
    build_planner_prompt,
    build_supervisor_prompt,
)
from research_agent.web.role_invocation import invoke_role_json
from research_agent.web.schemas import (
    CuratorOutput,
    Finding,
    PlannerOutput,
    PlannerSubtaskDraft,
    ResearchSubtask,
    SupervisorOutput,
    WebResearchStateDict,
    WebSource,
    check_required_field,
)


logger = logging.getLogger(__name__)


# ── payload validators ────────────────────────────────────────────────


def _validate_planner_payload(payload: dict[str, Any]) -> dict[str, Any]:
    check_required_field(payload, "research_title", str)
    check_required_field(payload, "subtasks", list)
    if not payload["subtasks"]:
        raise ValueError("subtasks must be a non-empty list")
    for subtask in payload["subtasks"]:
        if not isinstance(subtask, dict):
            raise ValueError("each subtask must be a dict")
        check_required_field(subtask, "question", str)
    return payload


def _validate_supervisor_payload(payload: dict[str, Any]) -> dict[str, Any]:
    valid_routes = {"continue_execution", "revise_plan", "curate", "fail"}
    if payload.get("route") not in valid_routes:
        raise ValueError(f"route must be one of {valid_routes}")
    check_required_field(payload, "reason", str)
    return payload


def _validate_curator_payload(payload: dict[str, Any]) -> dict[str, Any]:
    check_required_field(payload, "title", str)
    check_required_field(payload, "summary", str)
    # R-125: validate findings/sources structure to catch malformed LLM output early
    check_required_field(payload, "findings", list, allow_empty=True)
    check_required_field(payload, "sources", list, allow_empty=True)
    for i, item in enumerate(payload.get("findings", [])):
        if not isinstance(item, dict):
            raise ValueError(f"findings[{i}] must be a dict, got {type(item).__name__}")
    for i, item in enumerate(payload.get("sources", [])):
        if not isinstance(item, dict):
            raise ValueError(f"sources[{i}] must be a dict, got {type(item).__name__}")
    return payload


# ── output parsers ────────────────────────────────────────────────────


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

# ── GraphContext: dependency bundle for node closures ──────────────────


@dataclass
class GraphContext:
    """Bundle of dependencies needed by graph node closures.

    Passed to :func:`build_web_research_graph` instead of having node
    closures capture ``self`` from ``StateGraphRunner``.
    """

    chat_models: dict[str, ChatModelClient]
    executor: ResearchExecutor
    max_retrieval_rounds: int
    task_id: str
    _emit: Callable[..., None] = field(repr=False)
    _save_llm_call_artifact: Callable[..., None] = field(repr=False)
    _save_source_snapshots: Callable[..., None] = field(repr=False)


# ── route guard ───────────────────────────────────────────────────────


def route_after_supervise(state: WebResearchStateDict, max_retrieval_rounds: int) -> str:
    """Decide next node from supervisor's route, with safety guards.

    Extracted as a standalone function so tests can call it directly.
    """
    last_sup = state.get("last_supervisor_output")
    if last_sup is None:
        return "curate" if state.get("findings") and state.get("sources") else "fail"

    route: str = last_sup.route
    retrieval_round: int = state.get("retrieval_round", 0)

    if route == "continue_execution" and not last_sup.next_subtask_ids:
        return "curate" if state.get("findings") and state.get("sources") else "fail"

    if retrieval_round >= max_retrieval_rounds:
        if route in ("continue_execution", "revise_plan"):
            return "curate" if state.get("findings") and state.get("sources") else "fail"

    return route


# ── graph node functions ──────────────────────────────────────────────
# Extracted from build_web_research_graph so each node is independently
# testable and the graph builder stays focused on wiring (R-100).


def _plan_node(state: WebResearchStateDict, ctx: GraphContext) -> dict[str, Any]:
    task_id = ctx.task_id
    ctx._emit(task_id, "web_planning", "started", "Planning web research.")
    planner_prompt = build_planner_prompt(state)
    planner_payload = invoke_role_json(
        role_name="planner",
        prompt=planner_prompt,
        target_schema='{"research_title": "string", "subtasks": [{"question": "string"}]}',
        chat_model=ctx.chat_models["planner"],
        validator=_validate_planner_payload,
    )
    ctx._save_llm_call_artifact(task_id, "planner", planner_prompt, planner_payload, round_num=0)
    planner_output = PlannerOutput(
        research_title=planner_payload["research_title"],
        subtasks=[PlannerSubtaskDraft(question=s["question"]) for s in planner_payload["subtasks"]],
    )
    next_id = len(state.get("subtasks", [])) + 1
    new_subtasks = [
        ResearchSubtask(subtask_id=f"st_{next_id + i}", question=draft.question)
        for i, draft in enumerate(planner_output.subtasks)
    ]
    ctx._emit(task_id, "web_planning", "completed",
              f"Plan created with {len(new_subtasks)} subtasks.")
    return {
        "research_title": planner_output.research_title,
        "subtasks": new_subtasks,
        "route_history": ["plan"],
    }


def _execute_node(state: WebResearchStateDict, ctx: GraphContext) -> dict[str, Any]:
    task_id = ctx.task_id
    last_sup = state.get("last_supervisor_output")
    pending = [s for s in state["subtasks"] if s.status == "pending"]

    # R-120: Only filter by next_subtask_ids when the last supervisor
    # explicitly routed "continue_execution".  After "revise_plan" the
    # supervisor's next_subtask_ids are stale — filtering would skip
    # newly-created subtasks.
    if (
        last_sup is not None
        and last_sup.next_subtask_ids
        and last_sup.route == "continue_execution"
    ):
        pending = [s for s in pending if s.subtask_id in last_sup.next_subtask_ids]

    # R-121: Do NOT increment retrieval_round on an empty execute —
    # consuming a round budget without producing any evidence can
    # prematurely hit the max_retrieval_rounds guard.
    if not pending:
        return {"route_history": ["execute_round_skip"]}

    pending_ids = [s.subtask_id for s in pending]
    ctx._emit(task_id, "web_execution", "started", f"Executing {len(pending_ids)} subtasks.")
    executor_outputs = ctx.executor.execute(state, pending_ids, ctx.chat_models["executor"])

    all_findings: list[Finding] = []
    all_sources: list[WebSource] = []
    status_updates: list[ResearchSubtask] = []
    for output in executor_outputs:
        all_findings.extend(output.findings)
        all_sources.extend(output.sources)
        original = next(
            (st for st in state["subtasks"] if st.subtask_id == output.subtask_id), None
        )
        if original is not None:
            status_updates.append(ResearchSubtask(
                subtask_id=output.subtask_id,
                question=original.question,
                status=output.status,
            ))
        else:
            # R-122: executor produced output for a subtask not in state —
            # findings/sources are still collected but won't be linked.
            logger.warning(
                "Executor returned output for subtask %r not found in state; "
                "findings and sources collected but not linked to any subtask.",
                output.subtask_id,
            )

    new_round = state["retrieval_round"] + 1
    ctx._save_source_snapshots(task_id, state, new_sources=all_sources)
    ctx._emit(task_id, "web_execution", "completed", "Subtasks executed.")

    return {
        "executor_outputs": executor_outputs,
        "findings": all_findings,
        "sources": all_sources,
        "subtasks": status_updates,
        "retrieval_round": new_round,
        "route_history": [f"execute_round_{new_round}"],
    }


def _supervise_node(state: WebResearchStateDict, ctx: GraphContext) -> dict[str, Any]:
    task_id = ctx.task_id
    ctx._emit(task_id, "web_supervision", "started", "Evaluating research progress.")
    supervisor_prompt = build_supervisor_prompt(state)
    supervisor_payload = invoke_role_json(
        role_name="supervisor",
        prompt=supervisor_prompt,
        target_schema='{"route": "string", "reason": "string", "next_subtask_ids": ["string"], "skip_subtask_ids": ["string"], "plan_revision_request": "string|null", "research_gaps": ["string"], "saturation": false}',
        chat_model=ctx.chat_models["supervisor"],
        validator=_validate_supervisor_payload,
    )
    ctx._save_llm_call_artifact(
        task_id, "supervisor", supervisor_prompt, supervisor_payload,
        round_num=state["retrieval_round"],
    )
    supervisor_output = _parse_supervisor_output(supervisor_payload)

    skipped: list[ResearchSubtask] = []
    for sid in supervisor_output.skip_subtask_ids:
        original = next(
            (st for st in state["subtasks"] if st.subtask_id == sid), None
        )
        if original is not None and original.status == "pending":
            skipped.append(ResearchSubtask(
                subtask_id=sid,
                question=original.question,
                status="skipped",
            ))

    supervisor_items: list[dict[str, Any]] = []
    if supervisor_output.research_gaps:
        supervisor_items.extend(
            {"kind": "research_gap", "text": gap} for gap in supervisor_output.research_gaps
        )
    ctx._emit(task_id, "web_supervision", "completed", supervisor_output.reason,
              items=supervisor_items)

    return {
        "last_supervisor_output": supervisor_output,
        "research_gaps": supervisor_output.research_gaps,
        "subtasks": skipped,
        "route_history": [f"supervise:{supervisor_output.route}"],
    }


def _plan_revision_node(state: WebResearchStateDict, ctx: GraphContext) -> dict[str, Any]:
    task_id = ctx.task_id
    ctx._emit(task_id, "web_revision", "started", "Revising plan.")
    revision_prompt = build_planner_prompt(state, revision=True)
    revision_payload = invoke_role_json(
        role_name="planner_revision",
        prompt=revision_prompt,
        target_schema='{"research_title": "string", "subtasks": [{"question": "string"}]}',
        chat_model=ctx.chat_models["planner"],
        validator=_validate_planner_payload,
    )
    ctx._save_llm_call_artifact(
        task_id, "planner_revision", revision_prompt, revision_payload,
        round_num=state["retrieval_round"],
    )
    revision_output = PlannerOutput(
        research_title=revision_payload["research_title"],
        subtasks=[PlannerSubtaskDraft(question=s["question"])
                  for s in revision_payload["subtasks"]],
    )
    next_id = len(state["subtasks"]) + 1
    new_subtasks = [
        ResearchSubtask(subtask_id=f"st_{next_id + i}", question=draft.question)
        for i, draft in enumerate(revision_output.subtasks)
    ]
    ctx._emit(task_id, "web_revision", "completed",
              f"Plan revised with {len(new_subtasks)} new subtasks.")
    revision_ids = [st.subtask_id for st in new_subtasks]
    return {
        "research_title": revision_output.research_title,
        "subtasks": new_subtasks,
        "revision_subtask_ids": revision_ids,
        "route_history": ["plan_revision"],
    }


def _curate_node(state: WebResearchStateDict, ctx: GraphContext) -> dict[str, Any]:
    task_id = ctx.task_id
    ctx._emit(task_id, "web_curation", "started", "Curating findings.")
    curator_prompt = build_curator_prompt(state)
    curator_payload = invoke_role_json(
        role_name="curator",
        prompt=curator_prompt,
        target_schema='{"title": "string", "summary": "string", "findings": [], "sources": []}',
        chat_model=ctx.chat_models["curator"],
        validator=_validate_curator_payload,
    )
    ctx._save_llm_call_artifact(
        task_id, "curator", curator_prompt, curator_payload,
        round_num=state["retrieval_round"],
    )
    curator_output = _parse_curator_output(curator_payload)
    ctx._emit(task_id, "web_curation", "completed", "Curation completed.")
    return {"curator_output": curator_output}


def _fail_node(state: WebResearchStateDict, ctx: GraphContext) -> dict[str, Any]:
    ctx._emit(ctx.task_id, "web_curation", "failed",
              "Research could not complete successfully.")
    return {"route_history": ["fail"]}


def _route_edge(state: WebResearchStateDict, ctx: GraphContext) -> str:
    return route_after_supervise(state, ctx.max_retrieval_rounds)


# ── graph builder ─────────────────────────────────────────────────────


def build_web_research_graph(ctx: GraphContext) -> StateGraph:
    """Build and return a compiled LangGraph StateGraph for web research.

    Node functions are thin closures over extracted module-level functions,
    each receiving *ctx* for access to emit, chat_models, executor, and
    artifact-persistence helpers.
    """

    builder = StateGraph(WebResearchStateDict)

    builder.add_node("plan", lambda s: _plan_node(s, ctx))
    builder.add_node("execute", lambda s: _execute_node(s, ctx))
    builder.add_node("supervise", lambda s: _supervise_node(s, ctx))
    builder.add_node("plan_revision", lambda s: _plan_revision_node(s, ctx))
    builder.add_node("curate", lambda s: _curate_node(s, ctx))
    builder.add_node("fail", lambda s: _fail_node(s, ctx))

    builder.add_edge(START, "plan")
    builder.add_edge("plan", "execute")
    builder.add_edge("execute", "supervise")
    builder.add_edge("plan_revision", "execute")
    builder.add_edge("curate", END)
    builder.add_edge("fail", END)

    builder.add_conditional_edges(
        "supervise",
        lambda s: _route_edge(s, ctx),
        {
            "continue_execution": "execute",
            "revise_plan": "plan_revision",
            "curate": "curate",
            "fail": "fail",
        },
    )

    return builder
