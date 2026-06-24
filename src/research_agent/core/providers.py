from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

import httpx

from research_agent.core.config import ModelConfig, UserConfig


PostJson = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


class ChatModelClient(Protocol):
    def complete(self, prompt: str) -> str:
        ...


class EmbeddingClient(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


@dataclass
class OpenAICompatibleChatModel:
    config: ModelConfig
    post_json: PostJson | None = None

    @classmethod
    def from_config(cls, config: ModelConfig, *, post_json: PostJson | None = None) -> OpenAICompatibleChatModel:
        return cls(config=config, post_json=post_json)

    def complete(self, prompt: str) -> str:
        payload = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        response = self._post_json(_join_endpoint(self.config.base_url, "chat/completions"), payload)
        return str(response["choices"][0]["message"]["content"])

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = _auth_headers(self.config.api_key)
        if self.post_json is not None:
            return self.post_json(url, headers, payload)
        with httpx.Client(timeout=60) as client:
            response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return dict(response.json())


@dataclass
class OpenAICompatibleEmbeddingModel:
    config: ModelConfig
    post_json: PostJson | None = None

    @classmethod
    def from_config(cls, config: ModelConfig, *, post_json: PostJson | None = None) -> OpenAICompatibleEmbeddingModel:
        return cls(config=config, post_json=post_json)

    def embed(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.config.model, "input": texts}
        response = self._post_json(_join_endpoint(self.config.base_url, "embeddings"), payload)
        return [list(item["embedding"]) for item in response["data"]]

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = _auth_headers(self.config.api_key)
        if self.post_json is not None:
            return self.post_json(url, headers, payload)
        with httpx.Client(timeout=60) as client:
            response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return dict(response.json())


class FakeChatModelClient:
    def __init__(self, completions: list[str]) -> None:
        self.completions = list(completions)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.completions:
            return ""
        return self.completions.pop(0)


def build_role_chat_model_config(config: UserConfig, role: str) -> ModelConfig:
    role_overrides = config.role_chat_models.get(role)
    return role_overrides or config.chat_model


def _join_endpoint(base_url: str, endpoint: str) -> str:
    return f"{base_url.rstrip('/')}/{endpoint}"


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
