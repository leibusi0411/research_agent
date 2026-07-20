from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import httpx

from research_agent.core.config import ModelConfig, UserConfig


PostJson = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolCallResult:
    """Result from a native function/tool calling request."""
    name: str
    arguments: dict[str, Any]


class ChatModelClient(Protocol):
    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        ...

    def complete_tool(
        self, prompt: str, *, tool_name: str, tool_schema: dict[str, Any]
    ) -> ToolCallResult:
        """Call LLM with native function/tool calling.

        The returned :attr:`ToolCallResult.arguments` are provider-best-effort;
        the caller MUST validate them against *tool_schema*.
        """
        ...


class EmbeddingClient(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


def _post_json_request(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    post_json: PostJson | None = None,
) -> dict[str, Any]:
    """Shared POST JSON request helper for OpenAI-compatible models."""
    headers = _auth_headers(api_key)
    if post_json is not None:
        return post_json(url, headers, payload)
    with httpx.Client(timeout=httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=10.0)) as client:
        response = client.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return dict(response.json())


def _parse_llm_json(raw: str) -> dict[str, Any]:
    """Parse LLM-produced JSON string, with tolerance for common quirks.

    Some providers (DeepSeek) may produce JSON with single-quoted keys,
    trailing commas, or embedded markdown fences.  This function applies
    increasingly lenient fixes before giving up.
    """
    text = raw.strip()
    # Remove markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
    # Try direct parse first (fast path)
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("LLM JSON must be an object")
        return parsed
    except json.JSONDecodeError:
        pass
    # Try ast.literal_eval which natively handles single-quoted Python dicts
    # without damaging apostrophes inside double-quoted strings.
    try:
        parsed = ast.literal_eval(text)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, SyntaxError):
        pass
    # Replace single quotes with double quotes (common DeepSeek quirk).
    # NOTE: this regex will incorrectly replace apostrophes inside
    # double-quoted strings (e.g. "it's" → "it"s"), so it is only
    # attempted after the safer ast.literal_eval fallback above.
    try:
        fixed = re.sub(r"(?<!\\)'", '"', text)
        parsed = json.loads(fixed)
        if not isinstance(parsed, dict):
            raise ValueError("LLM JSON must be an object")
        return parsed
    except (json.JSONDecodeError, re.error):
        pass
    raise ValueError(f"LLM returned invalid JSON: {text[:200]}")


def _coerce_tool_arguments(arguments: Any) -> dict[str, Any]:
    """Return function-call arguments as an object, accepting common provider variants."""
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        return _parse_llm_json(arguments)
    raise ValueError(f"Tool call arguments must be a JSON object or string, got {type(arguments).__name__}")


@dataclass
class OpenAICompatibleChatModel:
    config: ModelConfig
    post_json: PostJson | None = None

    @classmethod
    def from_config(cls, config: ModelConfig, *, post_json: PostJson | None = None) -> OpenAICompatibleChatModel:
        return cls(config=config, post_json=post_json)

    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 16384,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = _post_json_request(
            _join_endpoint(self.config.base_url, "chat/completions"),
            payload,
            self.config.api_key,
            self.post_json,
        )
        return str(response["choices"][0]["message"]["content"])

    def complete_tool(
        self, prompt: str, *, tool_name: str, tool_schema: dict[str, Any]
    ) -> ToolCallResult:
        """Call with native function/tool calling.

        Does NOT force ``tool_choice`` because some providers (e.g. DeepSeek
        reasoning models) reject it outright.  When the model returns a text
        message instead of tool calls, the content is parsed as JSON as a
        fallback.
        """
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{
                "type": "function",
                "function": {
                    "name": tool_name,
                    "parameters": tool_schema,
                },
            }],
            "temperature": 0.1,
            "max_tokens": 16384,
        }
        response = _post_json_request(
            _join_endpoint(self.config.base_url, "chat/completions"),
            payload,
            self.config.api_key,
            self.post_json,
        )
        message = response["choices"][0]["message"]
        tool_calls = message.get("tool_calls")
        if tool_calls:
            tc = tool_calls[0]
            function = tc.get("function", {})
            return ToolCallResult(
                name=str(function.get("name", tool_name)),
                arguments=_coerce_tool_arguments(function.get("arguments", {})),
            )
        function_call = message.get("function_call")
        if function_call:
            return ToolCallResult(
                name=str(function_call.get("name", tool_name)),
                arguments=_coerce_tool_arguments(function_call.get("arguments", {})),
            )
        # Fallback: model returned text content instead of a tool call.
        content = str(message.get("content", ""))
        if "```" in content:
            content = content.split("```")[1].split("```")[0]
            if content.startswith("json"):
                content = content[4:]
        return ToolCallResult(
            name=tool_name,
            arguments=_parse_llm_json(content.strip()),
        )


@dataclass
class OpenAICompatibleEmbeddingModel:
    config: ModelConfig
    post_json: PostJson | None = None

    @classmethod
    def from_config(cls, config: ModelConfig, *, post_json: PostJson | None = None) -> OpenAICompatibleEmbeddingModel:
        return cls(config=config, post_json=post_json)

    def embed(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.config.model, "input": texts}
        response = _post_json_request(
            _join_endpoint(self.config.base_url, "embeddings"),
            payload,
            self.config.api_key,
            self.post_json,
        )
        return [list(item["embedding"]) for item in response["data"]]


def build_role_chat_model_config(config: UserConfig, role: str) -> ModelConfig:
    role_overrides = config.role_chat_models.get(role)
    return role_overrides or config.chat_model


def build_chat_models(config: UserConfig) -> dict[str, ChatModelClient]:
    """Build per-role ChatModelClient dict from config.

    Currently all roles use the same model (no per-role overrides in default
    config), but the dict-structured return allows per-role model overrides
    to take effect automatically once configured in config.toml.
    """
    chat_models: dict[str, ChatModelClient] = {}
    for role in ("planner", "executor", "supervisor", "curator"):
        role_config = build_role_chat_model_config(config, role)
        chat_models[role] = OpenAICompatibleChatModel.from_config(role_config)
    return chat_models


def _join_endpoint(base_url: str, endpoint: str) -> str:
    return f"{base_url.rstrip('/')}/{endpoint}"


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
