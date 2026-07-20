from __future__ import annotations

from typing import Any, Callable

from research_agent.core.errors import ResearchError
from research_agent.core.providers import ChatModelClient, ToolCallResult

Validator = Callable[[dict[str, Any]], Any]


def invoke_role_json(
    *,
    role_name: str,
    prompt: str,
    tool_name: str,
    tool_schema: dict[str, Any],
    chat_model: ChatModelClient,
    validator: Validator,
) -> dict[str, Any]:
    """Invoke an LLM role via native function/tool calling.

    The *validator* runs for application-level type/presence checks.
    LLM-call failures and schema-validation failures are reported with
    distinct error codes so callers can tell them apart.
    """
    try:
        result: ToolCallResult = chat_model.complete_tool(
            prompt=prompt,
            tool_name=tool_name,
            tool_schema=tool_schema,
        )
    except ResearchError:
        raise
    except Exception as exc:
        raise ResearchError(
            code="llm_call_failed",
            message=f"{role_name} LLM call failed: {exc}",
        ) from exc

    try:
        return validator(result.arguments)
    except ResearchError:
        raise
    except Exception as exc:
        raise ResearchError(
            code="schema_validation_failed",
            message=f"{role_name} function-call output failed schema validation: {exc}",
        ) from exc
