from __future__ import annotations

from typing import Any

from research_agent.web.context import (
    CuratorInput,
    ExecutorInput,
    PlannerInput,
    SupervisorInput,
    build_curator_context,
    build_executor_context,
    build_planner_context,
    build_supervisor_context,
)
from research_agent.web.schemas import WebResearchStateDict


def build_planner_prompt(state: WebResearchStateDict, *, revision: bool = False) -> str:
    context = build_planner_context(state)
    if revision:
        return _build_revision_planner_prompt(context)
    return _build_initial_planner_prompt(context)


def build_executor_tool_plan_prompt(
    state: WebResearchStateDict,
    subtask_id: str,
    *,
    tool_descriptions: str | None = None,
) -> str:
    """Build prompt for the executor to plan which tools to call.

    When *tool_descriptions* is provided it replaces the default hardcoded
    tool list, keeping the prompt in sync with the registry (R-128).
    """
    context = build_executor_context(state, subtask_id)
    return _render_tool_plan_prompt(context, tool_descriptions=tool_descriptions)


def build_executor_synthesis_prompt(
    state: WebResearchStateDict,
    subtask_id: str,
    tool_results: list[dict[str, Any]],
) -> str:
    """Build prompt for the executor to synthesize findings from tool results."""
    context = build_executor_context(state, subtask_id)
    return _render_synthesis_prompt(context, tool_results)


def build_supervisor_prompt(state: WebResearchStateDict) -> str:
    context = build_supervisor_context(state)
    return _render_supervisor_prompt(context)


def build_curator_prompt(state: WebResearchStateDict) -> str:
    context = build_curator_context(state)
    return _render_curator_prompt(context)


def _build_initial_planner_prompt(context: PlannerInput) -> str:
    return (
        "You are the Planner for a web research task.\n"
        "Your job is to create an initial research plan.\n\n"
        f"Research question: {context.original_question}\n\n"
        "Create 3-5 subtask question drafts that together will answer the research question.\n"
        "Each subtask should be a focused, searchable question.\n"
    )


def _build_revision_planner_prompt(context: PlannerInput) -> str:
    plan_lines = []
    for subtask in context.current_plan:
        status = subtask.status
        plan_lines.append(f"- [{status}] {subtask.question}")
    current_plan_text = "\n".join(plan_lines)

    gaps_text = ""
    if context.research_gaps:
        gaps_text = "\nResearch gaps identified:\n" + "\n".join(f"- {gap}" for gap in context.research_gaps)

    return (
        "You are the Planner for a web research task.\n"
        "Your job is to revise the existing research plan by adding new subtasks.\n\n"
        f"Research question: {context.original_question}\n\n"
        f"Current plan:\n{current_plan_text}\n"
        f"{gaps_text}\n\n"
        "Create 1-3 NEW subtask question drafts to append to the existing plan.\n"
        "Do NOT repeat existing subtasks. Focus on filling research gaps.\n"
    )


def _render_tool_plan_prompt(
    context: ExecutorInput,
    *,
    tool_descriptions: str | None = None,
) -> str:
    if tool_descriptions is None:
        tool_descriptions = (
            '1. web.search - Search the web. Arguments: {"query": "search query", "max_results": 5}\n'
            '2. web.fetch_extract - Fetch and extract text from a URL. Arguments: {"url": "https://..."}\n'
            '3. web.download_pdf - Download and extract text from a PDF. Arguments: {"url": "https://..."}\n'
        )
    return (
        "You are a Research Executor for a web research task.\n"
        "Your job is to plan tool calls to gather information for a specific subtask.\n\n"
        f"Original research question: {context.original_question}\n"
        f"Your subtask: {context.subtask.question}\n\n"
        "Available tools:\n"
        f"{tool_descriptions}\n"
        "Plan a series of tool calls to gather evidence for this subtask.\n"
        "Start with web.search to find relevant sources, then use web.fetch_extract or web.download_pdf to get details.\n"
        "Make 2-5 tool calls. Include at least one web.search call.\n"
    )


def _format_tool_result(index: int, result: dict) -> str:
    """Format a single tool result for inclusion in the synthesis prompt."""
    tool_name = result.get("tool", "unknown")
    status = result.get("status", "unknown")
    if status == "ok":
        data = result.get("data", {})
        if tool_name == "web.search":
            search_results = data.get("results", [])
            lines = [f"\n--- Tool Call {index}: {tool_name} (status: {status}) ---"]
            for j, sr in enumerate(search_results[:5], 1):
                title = sr.get("title", "No title")
                url = sr.get("url", "No URL")
                snippet = sr.get("content", sr.get("snippet", ""))[:200]
                lines.append(f"  Result {j}: {title}\n  URL: {url}\n  Snippet: {snippet}\n")
            return "\n".join(lines)
        else:
            text_preview = data.get("text", "")[:500]
            return (
                f"\n--- Tool Call {index}: {tool_name} (status: {status}) ---\n"
                f"URL: {data.get('url', 'N/A')}\n"
                f"Content preview: {text_preview}...\n"
            )
    else:
        error = result.get("error", "unknown error")
        message = result.get("message", "")
        return (
            f"\n--- Tool Call {index}: {tool_name} (status: {status}) ---\n"
            f"Error: {error} - {message}\n"
        )


def _render_synthesis_prompt(context: ExecutorInput, tool_results: list[dict]) -> str:
    results_text = "".join(
        _format_tool_result(i, result) for i, result in enumerate(tool_results, 1)
    )

    return (
        "You are a Research Executor for a web research task.\n"
        "Your job is to synthesize findings from the tool call results below.\n\n"
        f"Original research question: {context.original_question}\n"
        f"Your subtask: {context.subtask.question}\n\n"
        f"Tool call results:\n{results_text}\n\n"
        "Based on the tool results above, synthesize your findings.\n"
        "Extract key information, cite sources by their URLs.\n"
        "Your subtask_id is: " + context.subtask.subtask_id + ".\n\n"
        'If the tool results contain no useful information, set status to "failed" and provide a failure_reason.\n'
        "IMPORTANT: Use actual URLs and titles from the tool results, not placeholder values.\n"
    )


def _render_supervisor_prompt(context: SupervisorInput) -> str:
    plan_lines = []
    for subtask in context.current_plan:
        status = subtask.status
        plan_lines.append(f"- [{status}] {subtask.subtask_id}: {subtask.question}")
    current_plan_text = "\n".join(plan_lines)

    execution_lines = []
    for output in context.executor_outputs:
        status = output.status
        findings_count = len(output.findings)
        sources_count = len(output.sources)
        execution_lines.append(
            f"- {output.subtask_id}: status={status}, findings={findings_count}, sources={sources_count}"
        )
        for finding in output.findings:
            execution_lines.append(f"  Finding: {finding.text}")
    execution_text = "\n".join(execution_lines) if execution_lines else "(no executions yet)"

    return (
        "You are the Supervisor for a web research task.\n"
        "Your job is to decide the next step in the research workflow.\n\n"
        f"Original research question: {context.original_question}\n\n"
        f"Current plan:\n{current_plan_text}\n\n"
        f"Execution results:\n{execution_text}\n\n"
        "Based on the execution results, decide the next action:\n"
        '- "continue_execution" - Execute more pending subtasks\n'
        '- "revise_plan" - The plan needs revision (add new subtasks)\n'
        '- "curate" - Enough evidence gathered, ready to write the report\n'
        '- "fail" - Research cannot succeed (no useful findings)\n\n'
        'If route is "continue_execution", list the subtask_ids to execute in next_subtask_ids.\n'
        'If route is "revise_plan", describe what new subtasks are needed in plan_revision_request.\n'
        'If route is "curate", set saturation to true if research is comprehensive.\n'
    )


def _render_curator_prompt(context: CuratorInput) -> str:
    findings_lines = []
    for finding in context.findings:
        source_refs = ", ".join(finding.source_ids)
        findings_lines.append(f"- [{finding.finding_id}] {finding.text} (sources: {source_refs})")
    findings_text = "\n".join(findings_lines) if findings_lines else "(no findings)"

    sources_lines = []
    for source in context.sources:
        sources_lines.append(f"- [{source.source_id}] {source.title}: {source.url}")
    sources_text = "\n".join(sources_lines) if sources_lines else "(no sources)"

    return (
        "You are the Curator for a web research task.\n"
        "Your job is to synthesize findings into a coherent research summary.\n\n"
        f"Original research question: {context.original_question}\n\n"
        f"Findings:\n{findings_text}\n\n"
        f"Sources:\n{sources_text}\n\n"
        "Create a concise title and summary that answers the research question.\n"
        "Select the most relevant findings and sources.\n"
    )
