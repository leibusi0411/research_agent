from __future__ import annotations

import json
from typing import Any, Callable

from research_agent.core.errors import ResearchError
from research_agent.core.providers import ChatModelClient


Validator = Callable[[dict[str, Any]], Any]


def invoke_role_json(
    *,
    role_name: str,
    prompt: str,
    target_schema: str,
    chat_model: ChatModelClient,
    validator: Validator,
) -> Any:
    raw_output = chat_model.complete(prompt)
    try:
        return _parse_and_validate(raw_output, validator)
    except Exception as first_error:  # noqa: BLE001 - converted to one schema repair attempt
        repair_prompt = build_schema_repair_prompt(
            role_name=role_name,
            raw_output=raw_output,
            validation_error=str(first_error),
            target_schema=target_schema,
        )
        repaired_output = chat_model.complete(repair_prompt)
    try:
        return _parse_and_validate(repaired_output, validator)
    except Exception as second_error:  # noqa: BLE001 - normalized workflow failure
        raise ResearchError(
            code="schema_validation_failed",
            message=f"{role_name} output failed schema validation after one repair attempt: {second_error}",
        ) from second_error


def build_schema_repair_prompt(*, role_name: str, raw_output: str, validation_error: str, target_schema: str) -> str:
    return "\n".join(
        [
            f"You are repairing the JSON output for the {role_name} role.",
            "Return only corrected JSON. Do not include markdown.",
            "",
            "Target schema:",
            target_schema,
            "",
            "Validation error:",
            validation_error,
            "",
            "Raw invalid output:",
            raw_output,
        ]
    )


def _parse_and_validate(raw_output: str, validator: Validator) -> Any:
    parsed = json.loads(raw_output)
    if not isinstance(parsed, dict):
        raise ValueError("role output must be a JSON object")
    return validator(parsed)
