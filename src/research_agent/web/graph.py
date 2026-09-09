from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from research_agent.core.providers import ChatModelClient
from research_agent.web.executor import ResearchExecutor
from research_agent.web.prompt_builders import (
    build_curator_prompt,
    build_planner_prompt,
    build_planner_survey_prompt,
    build_supervisor_prompt,
)
from research_agent.web.role_invocation import invoke_role_json
from research_agent.web.schemas import (
    CuratorOutput,
    Finding,
    PlannerOutput,
    PlannerSubtaskDraft,
    PriorKnowledgeChunk,
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
    # ADR-0048: planner-side local_kb_search survey.  The retriever is the
    # same read-only hybrid retrieval the standalone Local RAG uses; the
    # updater refreshes a stale index before the survey.  Both are None when
    # the local knowledge base is unavailable (degrades to a web-only plan).
    local_retriever: Callable[[str], list[PriorKnowledgeChunk]] | None = None
    index_updater: Callable[[], dict[str, Any]] | None = None


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


# ── JSON Schema constants for native function calling ───────────────────


_PLANNER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "research_title": {"type": "string"},
        "subtasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    "required": ["research_title", "subtasks"],
}

_SUPERVISOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "route": {"type": "string", "enum": ["continue_execution", "revise_plan", "curate", "fail"]},
        "reason": {"type": "string"},
        "next_subtask_ids": {"type": "array", "items": {"type": "string"}},
        "skip_subtask_ids": {"type": "array", "items": {"type": "string"}},
        "plan_revision_request": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "research_gaps": {"type": "array", "items": {"type": "string"}},
        "saturation": {"type": "boolean"},
    },
    "required": ["route", "reason", "next_subtask_ids", "skip_subtask_ids", "research_gaps", "saturation"],
}

_CURATOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "subtask_id": {"type": "string"},
                    "text": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["finding_id", "subtask_id", "text", "source_ids"],
            },
        },
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "fetched_at": {"type": "string"},
                },
                "required": ["source_id", "title", "url", "fetched_at"],
            },
        },
    },
    "required": ["title", "summary", "findings", "sources"],
}


# ── graph node functions ──────────────────────────────────────────────
# Extracted from build_web_research_graph so each node is independently
# testable and the graph builder stays focused on wiring (R-100).


def _plan_node(state: WebResearchStateDict, ctx: GraphContext) -> dict[str, Any]:
    task_id = ctx.task_id
    ctx._emit(task_id, "web_planning", "started", "Planning web research.")
    local_survey = _run_local_survey(state, ctx, phase="web_planning")
    planner_prompt = build_planner_prompt(state, local_survey=local_survey)
    planner_payload = invoke_role_json(
        role_name="planner",
        prompt=planner_prompt,
        tool_name="plan_output",
        tool_schema=_PLANNER_SCHEMA,
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
        tool_name="supervisor_output",
        tool_schema=_SUPERVISOR_SCHEMA,
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


# ── planner local survey (ADR-0048: local_kb_search) ──────────────────

_LOCAL_SURVEY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "queries": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["queries"],
}

_SURVEY_QUERY_CAP = 3


def _validate_survey_payload(payload: dict[str, Any]) -> dict[str, Any]:
    queries = payload.get("queries")
    if not isinstance(queries, list) or not all(isinstance(q, str) for q in queries):
        raise ValueError("queries must be a list of strings")
    return payload


def _run_local_survey(
    state: WebResearchStateDict, ctx: GraphContext, phase: str
) -> list[dict[str, Any]]:
    """Run the planner's local_kb_search survey before final planning.

    Bounded by design: one structured LLM call proposes up to
    ``_SURVEY_QUERY_CAP`` targeted queries, the queries run in parallel
    through the (read-only) local retriever, and merged results are deduped
    by text+source with a hit-count boost.  Any failure degrades to an empty
    survey — this auxiliary phase must never kill the planning phase.

    Emits only ``progress`` events under the *calling node's* phase — no
    started/completed boundary events, so the phase stream stays monotonic
    (ADR-0023) even when the survey runs during plan revision.
    """
    task_id = ctx.task_id
    if ctx.local_retriever is None:
        return []
    ctx._emit(task_id, phase, "progress", "Surveying local knowledge base.")

    # Refresh a stale index before surveying when the pending change set is
    # small (ADR-0048); a large change set keeps the stale index and degrades.
    if ctx.index_updater is not None:
        try:
            update_result = ctx.index_updater()
            updated_files = int(update_result.get("updated_files", 0))
            if updated_files:
                ctx._emit(
                    task_id, phase, "progress",
                    f"Local index incrementally updated ({updated_files} files).",
                )
        except Exception:
            logger.warning("Local index auto-update failed; continuing with the current index", exc_info=True)

    survey_prompt = build_planner_survey_prompt(state)
    try:
        payload = invoke_role_json(
            role_name="planner_local_survey",
            prompt=survey_prompt,
            tool_name="local_kb_search",
            tool_schema=_LOCAL_SURVEY_SCHEMA,
            chat_model=ctx.chat_models["planner"],
            validator=_validate_survey_payload,
        )
        ctx._save_llm_call_artifact(
            task_id, "planner_local_survey", survey_prompt, payload,
            round_num=state.get("retrieval_round", 0),
        )
    except Exception:
        logger.warning("Local knowledge survey failed; planning without it", exc_info=True)
        return []

    queries = [
        query.strip()
        for query in payload.get("queries", [])
        if isinstance(query, str) and query.strip()
    ][:_SURVEY_QUERY_CAP]
    if not queries:
        return []

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    merge_lock = threading.Lock()

    def run_query(query: str) -> None:
        try:
            chunks = ctx.local_retriever(query) or []  # type: ignore[misc]
            for chunk in chunks:
                with merge_lock:
                    key = (chunk.source_path, chunk.text)
                    entry = merged.get(key)
                    if entry is None:
                        merged[key] = {
                            "query": query,
                            "text": chunk.text,
                            "source_path": chunk.source_path,
                            "heading_path": list(chunk.heading_path),
                            "hits": 1,
                        }
                    else:
                        entry["hits"] += 1
                        if query not in entry["query"]:
                            entry["query"] = f"{entry['query']} | {query}"
        except Exception:
            # Malformed chunk objects must not bubble up and kill planning.
            logger.warning("Local survey retrieval failed for query %r", query, exc_info=True)

    with ThreadPoolExecutor(max_workers=min(_SURVEY_QUERY_CAP, len(queries))) as pool:
        list(pool.map(run_query, queries))

    results = sorted(merged.values(), key=lambda item: -item["hits"])
    ctx._emit(
        task_id, phase, "progress",
        f"Local survey: {len(queries)} queries, {len(results)} unique chunks.",
    )
    return results


def _plan_revision_node(state: WebResearchStateDict, ctx: GraphContext) -> dict[str, Any]:
    task_id = ctx.task_id
    ctx._emit(task_id, "web_revision", "started", "Revising plan.")
    local_survey = _run_local_survey(state, ctx, phase="web_revision")
    revision_prompt = build_planner_prompt(state, revision=True, local_survey=local_survey)
    revision_payload = invoke_role_json(
        role_name="planner_revision",
        prompt=revision_prompt,
        tool_name="plan_output",
        tool_schema=_PLANNER_SCHEMA,
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
        tool_name="curator_output",
        tool_schema=_CURATOR_SCHEMA,
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
