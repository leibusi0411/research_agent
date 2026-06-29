from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

import httpx

from research_agent.core.config import ModelConfig, UserConfig


PostJson = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


class ChatModelClient(Protocol):
    def complete(self, prompt: str, *, json_mode: bool = False) -> str:
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
