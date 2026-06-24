from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from research_agent.core.errors import ResearchError


DEFAULT_RESEARCH = {
    "max_retrieval_rounds": 3,
    "max_concurrent_subtasks": 3,
}
DEFAULT_WEB_TOOLS = {
    "request_timeout_seconds": 45,
    "pdf_timeout_seconds": 90,
    "max_response_bytes": 20_971_520,
    "max_pdf_bytes": 104_857_600,
    "search_top_k": 10,
    "search_top_k_max": 20,
    "tool_retries": 2,
}


@dataclass(frozen=True)
class WorkspaceConfig:
    default_workspace: Path
    knowledge_base_path: Path


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class SearchConfig:
    provider: str
    api_key: str


@dataclass(frozen=True)
class ResearchConfig:
    max_retrieval_rounds: int
    max_concurrent_subtasks: int


@dataclass(frozen=True)
class IndexConfig:
    backend: str


@dataclass(frozen=True)
class WebToolsConfig:
    request_timeout_seconds: int
    pdf_timeout_seconds: int
    max_response_bytes: int
    max_pdf_bytes: int
    search_top_k: int
    search_top_k_max: int
    tool_retries: int


@dataclass(frozen=True)
class UserConfig:
    workspace: WorkspaceConfig
    research: ResearchConfig
    chat_model: ModelConfig
    role_chat_models: dict[str, ModelConfig]
    embedding_model: ModelConfig
    search: SearchConfig
    index: IndexConfig
    web_tools: WebToolsConfig


@dataclass(frozen=True)
class InitConfigRequest:
    default_workspace: Path
    knowledge_base_path: Path
    chat_base_url: str
    chat_api_key: str
    chat_model: str
    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    search_api_key: str


def default_config_path() -> Path:
    override = os.environ.get("RESEARCH_AGENT_CONFIG_PATH")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "research_agent" / "config.toml"
    return Path.home() / ".config" / "research_agent" / "config.toml"


def resolve_user_path(path: Path, launch_cwd: Path | None = None) -> Path:
    if path.is_absolute():
        return path
    base = launch_cwd or Path.cwd()
    return (base / path).resolve()


def init_user_config(
    request: InitConfigRequest,
    config_path: Path | None = None,
    launch_cwd: Path | None = None,
) -> Path:
    target_config_path = config_path or default_config_path()
    _validate_raw_path("Default Workspace", request.default_workspace)
    _validate_raw_path("Knowledge Base path", request.knowledge_base_path)
    default_workspace = resolve_user_path(Path(request.default_workspace), launch_cwd)
    knowledge_base_path = resolve_user_path(Path(request.knowledge_base_path), launch_cwd)

    _validate_init_request(
        request=InitConfigRequest(
            default_workspace=default_workspace,
            knowledge_base_path=knowledge_base_path,
            chat_base_url=request.chat_base_url,
            chat_api_key=request.chat_api_key,
            chat_model=request.chat_model,
            embedding_base_url=request.embedding_base_url,
            embedding_api_key=request.embedding_api_key,
            embedding_model=request.embedding_model,
            search_api_key=request.search_api_key,
        )
    )

    default_workspace.mkdir(parents=True, exist_ok=True)
    target_config_path.parent.mkdir(parents=True, exist_ok=True)
    target_config_path.write_text(
        _render_config_toml(
            default_workspace=default_workspace,
            knowledge_base_path=knowledge_base_path,
            request=request,
        ),
        encoding="utf-8",
    )
    return target_config_path


def load_user_config(config_path: Path | None = None) -> UserConfig:
    target_config_path = config_path or default_config_path()
    if not target_config_path.exists():
        raise ResearchError(
            code="config_missing",
            message="User config is missing. Run research-agent init first.",
        )

    try:
        data = tomllib.loads(target_config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ResearchError(code="config_invalid", message=f"Invalid config TOML: {exc}") from exc

    return _parse_user_config(data)


def _parse_user_config(data: dict) -> UserConfig:
    try:
        workspace = data["workspace"]
        research = {**DEFAULT_RESEARCH, **data.get("research", {})}
        chat_model = data["chat_model"]
        embedding_model = data["embedding_model"]
        search = data["search"]
        index = data.get("index", {"backend": "sqlite_fts5_chroma"})
        web_tools = {**DEFAULT_WEB_TOOLS, **data.get("web_tools", {})}
        return UserConfig(
            workspace=WorkspaceConfig(
                default_workspace=Path(workspace["default_workspace"]),
                knowledge_base_path=Path(workspace["knowledge_base_path"]),
            ),
            research=ResearchConfig(
                max_retrieval_rounds=int(research["max_retrieval_rounds"]),
                max_concurrent_subtasks=int(research["max_concurrent_subtasks"]),
            ),
            chat_model=ModelConfig(
                provider=chat_model.get("provider", "openai_compatible"),
                base_url=chat_model["base_url"],
                api_key=chat_model["api_key"],
                model=chat_model["model"],
            ),
            role_chat_models=_parse_role_chat_models(chat_model),
            embedding_model=ModelConfig(
                provider=embedding_model.get("provider", "openai_compatible"),
                base_url=embedding_model["base_url"],
                api_key=embedding_model["api_key"],
                model=embedding_model["model"],
            ),
            search=SearchConfig(provider=search.get("provider", "tavily"), api_key=search["api_key"]),
            index=IndexConfig(backend=index.get("backend", "sqlite_fts5_chroma")),
            web_tools=WebToolsConfig(**{key: int(value) for key, value in web_tools.items()}),
        )
    except KeyError as exc:
        raise ResearchError(code="config_invalid", message=f"Missing config field: {exc.args[0]}") from exc
    except (TypeError, ValueError) as exc:
        raise ResearchError(code="config_invalid", message=f"Invalid config value: {exc}") from exc


def _validate_init_request(request: InitConfigRequest) -> None:
    if not Path(request.knowledge_base_path).is_dir():
        raise ResearchError(
            code="config_invalid",
            message="Knowledge Base path must be an existing directory.",
        )
    for label, value in [
        ("Chat model base URL", request.chat_base_url),
        ("Embedding model base URL", request.embedding_base_url),
    ]:
        if not _is_valid_url(value):
            raise ResearchError(code="config_invalid", message=f"{label} must be a valid URL.")
    for label, value in [
        ("Chat model API key", request.chat_api_key),
        ("Chat model name", request.chat_model),
        ("Embedding model API key", request.embedding_api_key),
        ("Embedding model name", request.embedding_model),
        ("Search API key", request.search_api_key),
    ]:
        if not value.strip():
            raise ResearchError(code="config_invalid", message=f"{label} must be non-empty.")


def _parse_role_chat_models(chat_model: dict) -> dict[str, ModelConfig]:
    global_config = ModelConfig(
        provider=chat_model.get("provider", "openai_compatible"),
        base_url=chat_model["base_url"],
        api_key=chat_model["api_key"],
        model=chat_model["model"],
    )
    roles: dict[str, ModelConfig] = {}
    for role in ["planner", "executor", "supervisor", "curator"]:
        override = chat_model.get(role)
        if not isinstance(override, dict):
            continue
        roles[role] = ModelConfig(
            provider=override.get("provider", global_config.provider),
            base_url=override.get("base_url", global_config.base_url),
            api_key=override.get("api_key", global_config.api_key),
            model=override.get("model", global_config.model),
        )
    return roles


def _validate_raw_path(label: str, value: Path) -> None:
    raw_value = str(value).strip()
    if not raw_value or raw_value == ".":
        raise ResearchError(code="config_invalid", message=f"{label} must be non-empty.")


def _is_valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _render_config_toml(
    default_workspace: Path,
    knowledge_base_path: Path,
    request: InitConfigRequest,
) -> str:
    return "\n".join(
        [
            "[workspace]",
            f'default_workspace = "{_toml_string(default_workspace)}"',
            f'knowledge_base_path = "{_toml_string(knowledge_base_path)}"',
            "",
            "[research]",
            "max_retrieval_rounds = 3",
            "max_concurrent_subtasks = 3",
            "",
            "[chat_model]",
            'provider = "openai_compatible"',
            f'base_url = "{_toml_string(request.chat_base_url)}"',
            f'api_key = "{_toml_string(request.chat_api_key)}"',
            f'model = "{_toml_string(request.chat_model)}"',
            "",
            "[embedding_model]",
            'provider = "openai_compatible"',
            f'base_url = "{_toml_string(request.embedding_base_url)}"',
            f'api_key = "{_toml_string(request.embedding_api_key)}"',
            f'model = "{_toml_string(request.embedding_model)}"',
            "",
            "[search]",
            'provider = "tavily"',
            f'api_key = "{_toml_string(request.search_api_key)}"',
            "",
            "[index]",
            'backend = "sqlite_fts5_chroma"',
            "",
            "[web_tools]",
            "request_timeout_seconds = 45",
            "pdf_timeout_seconds = 90",
            "max_response_bytes = 20971520",
            "max_pdf_bytes = 104857600",
            "search_top_k = 10",
            "search_top_k_max = 20",
            "tool_retries = 2",
            "",
        ]
    )


def _toml_string(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')
