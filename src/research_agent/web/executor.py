from __future__ import annotations

import logging
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from research_agent.core.errors import ResearchError
from research_agent.core.ids import utc_now_iso
from research_agent.core.providers import ChatModelClient
from research_agent.web.prompt_builders import (
    build_executor_tool_plan_prompt,
    build_executor_synthesis_prompt,
)
from research_agent.web.role_invocation import invoke_role_json
from research_agent.web.schemas import (
    ExecutorOutput,
    Finding,
    WebResearchStateDict,
    WebSource,
    check_required_field,
)
from research_agent.web.tools import WEB_RESEARCH_WORKFLOW, ToolGateway

logger = logging.getLogger(__name__)

# ── JSON Schema constants for native function calling ───────────────────

_EXECUTOR_TOOL_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["name", "arguments"],
            },
        },
    },
    "required": ["tool_calls"],
}

_EXECUTOR_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subtask_id": {"type": "string"},
        "status": {"type": "string", "enum": ["completed", "failed"]},
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
        "failure_reason": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": ["subtask_id", "status", "findings", "sources"],
}


def _normalize_tool_call_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize common LLM/provider variants into {"tool_calls": [...]}."""
    if "tool_calls" not in payload and "name" in payload:
        payload = {"tool_calls": [payload]}

    tool_calls = payload.get("tool_calls")
    if isinstance(tool_calls, dict):
        tool_calls = [tool_calls]

    normalized: list[dict[str, Any]] = []
    if isinstance(tool_calls, list):
        for item in tool_calls:
            if not isinstance(item, dict):
                normalized.append(item)
                continue
            if "function" in item and isinstance(item["function"], dict):
                function = item["function"]
                arguments = function.get("arguments", {})
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                normalized.append({
                    "name": function.get("name"),
                    "arguments": arguments,
                })
            else:
                if isinstance(item.get("arguments"), str):
                    item = {**item, "arguments": json.loads(item["arguments"])}
                elif "arguments" not in item:
                    # Some models flatten arguments into the tool-call object
                    # (e.g. {"name": "web.search", "query": "..."} instead of
                    # nesting them) — collect the remaining keys as arguments
                    # so the gateway can validate them (R-205 family).
                    item = {
                        "name": item.get("name", ""),
                        "arguments": {k: v for k, v in item.items() if k != "name"},
                    }
                normalized.append(item)
    else:
        normalized = tool_calls

    return {**payload, "tool_calls": normalized}


def _validate_tool_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_tool_call_payload(payload)
    check_required_field(payload, "tool_calls", list, allow_empty=True)
    for tc in payload["tool_calls"]:
        if not isinstance(tc, dict):
            raise ValueError("tool_calls items must be objects")
        check_required_field(tc, "name", str)
        check_required_field(tc, "arguments", dict, allow_empty=True)
    return payload


def _validate_executor_payload(payload: dict[str, Any]) -> dict[str, Any]:
    check_required_field(payload, "subtask_id", str)
    if payload.get("status") not in ("completed", "failed"):
        raise ValueError("status must be 'completed' or 'failed'")
    check_required_field(payload, "findings", list, allow_empty=True)
    check_required_field(payload, "sources", list, allow_empty=True)
    # R-125: validate list element types to prevent AttributeError in parser
    for i, item in enumerate(payload.get("findings", [])):
        if not isinstance(item, dict):
            raise ValueError(f"findings[{i}] must be a dict, got {type(item).__name__}")
    for i, item in enumerate(payload.get("sources", [])):
        if not isinstance(item, dict):
            raise ValueError(f"sources[{i}] must be a dict, got {type(item).__name__}")
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


class ResearchExecutor:
    """Executes research subtasks using tool calls and LLM synthesis."""

    def __init__(
        self,
        *,
        tool_gateway: ToolGateway,
        max_concurrent_subtasks: int = 3,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.tool_gateway = tool_gateway
        self.max_concurrent_subtasks = max_concurrent_subtasks
        self.on_progress = on_progress

    def _build_tool_descriptions(self) -> str:
        """Build a human-readable tool list string from the registry (R-128)."""
        lines: list[str] = []
        for idx, name in enumerate(self.tool_gateway.registry.names(), 1):
            spec = self.tool_gateway.registry.get(name)
            args_desc = ", ".join(
                f'"{k}"' for k, v in spec.input_schema.items() if v.get("required")
            )
            lines.append(f"{idx}. {name} - Arguments: {{{args_desc}}}")
        return "\n".join(lines) if lines else "(no tools available)"

    def execute(
        self,
        state: WebResearchStateDict,
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
                subtask_question = next(
                    (s.question for s in state["subtasks"] if s.subtask_id == subtask_id),
                    subtask_id,
                )
                try:
                    output = future.result()
                    outputs.append(output)
                    if self.on_progress:
                        self.on_progress({
                            "kind": "subtask_completed",
                            "subtask_id": subtask_id,
                            "question": subtask_question,
                            "status": output.status,
                            "finding_count": len(output.findings),
                            "source_count": len(output.sources),
                        })
                except Exception as exc:
                    logger.exception("Subtask %s failed", subtask_id)
                    outputs.append(ExecutorOutput(
                        subtask_id=subtask_id,
                        status="failed",
                        findings=[],
                        sources=[],
                        failure_reason=str(exc),
                    ))
                    if self.on_progress:
                        self.on_progress({
                            "kind": "subtask_failed",
                            "subtask_id": subtask_id,
                            "question": subtask_question,
                            "error": str(exc),
                        })

        return outputs

    def _execute_single(
        self,
        state: WebResearchStateDict,
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

    def _plan_tool_calls(
        self,
        state: WebResearchStateDict,
        subtask_id: str,
        chat_model: ChatModelClient,
    ) -> dict[str, Any]:
        """Ask the LLM to plan which tools to call for a subtask."""
        tool_plan_prompt = build_executor_tool_plan_prompt(
            state, subtask_id,
            tool_descriptions=self._build_tool_descriptions(),
        )
        return invoke_role_json(
            role_name="executor",
            prompt=tool_plan_prompt,
            tool_name="executor_tool_plan",
            tool_schema=_EXECUTOR_TOOL_PLAN_SCHEMA,
            chat_model=chat_model,
            validator=_validate_tool_plan_payload,
        )

    def _execute_tool_calls(
        self,
        tool_plan: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Execute the planned tool calls and collect results."""
        tool_results: list[dict[str, Any]] = []
        for tc in tool_plan.get("tool_calls", []):
            tool_name = tc.get("name", "unknown")
            tool_input = tc.get("arguments", {})
            result = self.tool_gateway.call(WEB_RESEARCH_WORKFLOW, tc)
            tool_results.append({
                "tool": tool_name,
                "arguments": tool_input,
                "status": result.status,
                "data": result.data,
                "error": result.error,
                "message": result.message,
            })
            if self.on_progress:
                self.on_progress({
                    "kind": "tool_call",
                    "name": tool_name,
                    "input": tool_input.get("query", tool_input.get("url", str(tool_input))),
                })
        return tool_results

    def _synthesize_findings(
        self,
        state: WebResearchStateDict,
        subtask_id: str,
        chat_model: ChatModelClient,
        tool_results: list[dict[str, Any]],
    ) -> ExecutorOutput:
        """Ask the LLM to synthesize findings from tool results."""
        synthesis_prompt = build_executor_synthesis_prompt(state, subtask_id, tool_results)
        payload = invoke_role_json(
            role_name="executor",
            prompt=synthesis_prompt,
            tool_name="executor_synthesis",
            tool_schema=_EXECUTOR_SYNTHESIS_SCHEMA,
            chat_model=chat_model,
            validator=_validate_executor_payload,
        )
        executor_output = _parse_executor_output(payload, subtask_id)
        if self.on_progress:
            for f in executor_output.findings:
                self.on_progress({
                    "kind": "finding",
                    "text": f.text,
                    "subtask_id": subtask_id,
                })
            for s in executor_output.sources:
                self.on_progress({
                    "kind": "source",
                    "title": s.title,
                    "url": s.url,
                })
        return executor_output

    def _execute_with_tools(
        self,
        state: WebResearchStateDict,
        subtask_id: str,
        chat_model: ChatModelClient,
    ) -> ExecutorOutput:
        tool_plan = self._plan_tool_calls(state, subtask_id, chat_model)

        unknown_tools = [
            tc.get("name", "unknown")
            for tc in tool_plan.get("tool_calls", [])
            if isinstance(tc.get("name"), str) and not self.tool_gateway.registry.has(tc["name"])
        ]
        if unknown_tools:
            return ExecutorOutput(
                subtask_id=subtask_id,
                status="failed",
                findings=[],
                sources=[],
                failure_reason=f"Unknown tool(s) in plan: {', '.join(unknown_tools)}",
            )

        tool_results = self._execute_tool_calls(tool_plan)

        if not tool_results:
            return ExecutorOutput(
                subtask_id=subtask_id,
                status="failed",
                findings=[],
                sources=[],
                failure_reason="Executor LLM returned no tool calls for this subtask.",
            )

        return self._synthesize_findings(state, subtask_id, chat_model, tool_results)
