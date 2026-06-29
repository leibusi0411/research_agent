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
    raw_output = chat_model.complete(prompt, json_mode=True)
    try:
        return _parse_and_validate(raw_output, validator)
    except Exception as first_error:  # noqa: BLE001 - converted to one schema repair attempt
        # Save before implicit `del first_error` at end of except block (PEP 3110)
        _original_error_str = str(first_error)
        repaired_output: str | None = None
        try:
            repair_prompt = build_schema_repair_prompt(
                role_name=role_name,
                raw_output=raw_output,
                validation_error=_original_error_str,
                target_schema=target_schema,
            )
            repaired_output = chat_model.complete(repair_prompt)
        except Exception as repair_error:  # noqa: BLE001 - LLM call failure during repair
            raise ResearchError(
                code="schema_validation_failed",
                message=(
                    f"{role_name} schema repair LLM call failed "
                    f"(original validation error: {_original_error_str[:200]}): {repair_error}"
                ),
            ) from repair_error
        if repaired_output is None:
            raise ResearchError(
                code="schema_validation_failed",
                message=f"{role_name} schema repair produced no output (original error: {_original_error_str[:200]})",
            )
    try:
        return _parse_and_validate(repaired_output, validator)
    except Exception as second_error:  # noqa: BLE001 - normalized workflow failure
        raise ResearchError(
            code="schema_validation_failed",
            message=(
                f"{role_name} output failed schema validation after one repair attempt "
                f"(original validation error: {_original_error_str[:200]}): {second_error}"
            ),
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
