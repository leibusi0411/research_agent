import os
import tomllib
from pathlib import Path

import pytest

from research_agent.core.config import InitConfigRequest, load_user_config
from research_agent.core.errors import ResearchError
from research_agent.core.service import CoreService


def valid_init_request(default_workspace: Path, knowledge_base_path: Path) -> InitConfigRequest:
    return InitConfigRequest(
        default_workspace=default_workspace,
        knowledge_base_path=knowledge_base_path,
        chat_base_url="https://models.example/v1",
        chat_api_key="chat-key",
        chat_model="chat-model",
        embedding_base_url="https://embeddings.example/v1",
        embedding_api_key="embedding-key",
        embedding_model="embedding-model",
        search_api_key="search-key",
    )


def test_core_service_init_writes_user_config_and_workspace(tmp_path):
    config_path = tmp_path / "config.toml"
    vault = tmp_path / "vault"
    workspace = tmp_path / "runtime"
    vault.mkdir()

    service = CoreService(default_workspace=workspace, config_path=config_path)
    written_path = service.init_config(valid_init_request(workspace, vault))

    assert written_path == config_path
    assert workspace.is_dir()
    assert (workspace / "tasks").is_dir()
    assert (workspace / "indexes" / "local").is_dir()
    assert (workspace / "reports" / "web").is_dir()
    assert (workspace / "logs").is_dir()

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert data["workspace"]["default_workspace"] == str(workspace)
    assert data["workspace"]["knowledge_base_path"] == str(vault)
    assert data["research"] == {
        "max_retrieval_rounds": 3,
        "max_concurrent_subtasks": 3,
        "inject_local_context": True,
    }
    assert data["chat_model"] == {
        "provider": "openai_compatible",
        "base_url": "https://models.example/v1",
        "api_key": "chat-key",
        "model": "chat-model",
    }
    assert data["embedding_model"]["model"] == "embedding-model"
    assert data["search"] == {"provider": "tavily", "api_key": "search-key"}
    assert data["index"] == {"backend": "sqlite_fts5_chroma"}
    assert data["web_tools"]["tool_retries"] == 2


def test_core_service_init_updates_task_store_to_resolved_workspace(tmp_path):
    config_path = tmp_path / "config.toml"
    original_workspace = tmp_path / "placeholder"
    workspace = tmp_path / "runtime"
    vault = tmp_path / "vault"
    vault.mkdir()

    service = CoreService(default_workspace=original_workspace, config_path=config_path)
    service.init_config(valid_init_request(workspace, vault))

    assert service.workspace.root == workspace
    assert service.task_store.db_path == workspace / "tasks.sqlite"


def test_init_resolves_relative_paths_against_launch_cwd(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    launch_cwd = tmp_path / "launch"
    launch_cwd.mkdir()
    (launch_cwd / "vault").mkdir()
    monkeypatch.chdir(launch_cwd)

    service = CoreService(default_workspace=tmp_path / "placeholder", config_path=config_path)
    service.init_config(
        valid_init_request(Path("runtime"), Path("vault")),
        launch_cwd=launch_cwd,
    )

    loaded = load_user_config(config_path)
    assert loaded.workspace.default_workspace == launch_cwd / "runtime"
    assert loaded.workspace.knowledge_base_path == launch_cwd / "vault"


def test_init_rejects_invalid_required_fields(tmp_path):
    config_path = tmp_path / "config.toml"
    workspace = tmp_path / "runtime"
    missing_vault = tmp_path / "missing-vault"
    service = CoreService(default_workspace=workspace, config_path=config_path)

    with pytest.raises(ResearchError) as exc_info:
        service.init_config(valid_init_request(workspace, missing_vault))

    assert exc_info.value.to_dict() == {
        "code": "config_invalid",
        "message": "Knowledge Base path must be an existing directory.",
    }
    assert not config_path.exists()


def test_init_rejects_empty_required_paths(tmp_path):
    config_path = tmp_path / "config.toml"
    service = CoreService(default_workspace=tmp_path / "placeholder", config_path=config_path)

    with pytest.raises(ResearchError) as exc_info:
        service.init_config(valid_init_request(Path(""), tmp_path))

    assert exc_info.value.code == "config_invalid"
    assert "Default Workspace" in exc_info.value.message


def test_missing_config_returns_config_missing(tmp_path):
    with pytest.raises(ResearchError) as exc_info:
        load_user_config(tmp_path / "missing.toml")

    assert exc_info.value.to_dict() == {
        "code": "config_missing",
        "message": "User config is missing. Configure in the Settings page first.",
    }


def test_malformed_existing_config_returns_config_invalid(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workspace]\nknowledge_base_path = \"D:/vault\"\n", encoding="utf-8")

    with pytest.raises(ResearchError) as exc_info:
        load_user_config(config_path)

    assert exc_info.value.code == "config_invalid"
    assert "Missing config field" in exc_info.value.message


def test_research_config_inject_local_context_defaults_true(tmp_path):
    config_path = tmp_path / "config.toml"
    vault = tmp_path / "vault"
    vault.mkdir()
    service = CoreService(default_workspace=tmp_path / "runtime", config_path=config_path)
    service.init_config(valid_init_request(tmp_path / "runtime", vault))

    loaded = load_user_config(config_path)

    assert loaded.research.inject_local_context is True


def test_research_config_inject_local_context_parses_false(tmp_path):
    config_path = tmp_path / "config.toml"
    vault = tmp_path / "vault"
    vault.mkdir()
    service = CoreService(default_workspace=tmp_path / "runtime", config_path=config_path)
    service.init_config(valid_init_request(tmp_path / "runtime", vault))
    content = config_path.read_text(encoding="utf-8").replace(
        "inject_local_context = true",
        "inject_local_context = false",
    )
    config_path.write_text(content, encoding="utf-8")

    loaded = load_user_config(config_path)

    assert loaded.research.inject_local_context is False


def test_research_config_inject_local_context_rejects_non_bool(tmp_path):
    config_path = tmp_path / "config.toml"
    vault = tmp_path / "vault"
    vault.mkdir()
    service = CoreService(default_workspace=tmp_path / "runtime", config_path=config_path)
    service.init_config(valid_init_request(tmp_path / "runtime", vault))
    content = config_path.read_text(encoding="utf-8").replace(
        "inject_local_context = true",
        'inject_local_context = "false"',
    )
    config_path.write_text(content, encoding="utf-8")

    with pytest.raises(ResearchError) as excinfo:
        load_user_config(config_path)

    assert excinfo.value.code == "config_invalid"


# ---------------------------------------------------------------------------
# Query rewrite / rerank toggles + [rerank_model] section + local_summarizer slot
# ---------------------------------------------------------------------------


def test_research_config_ignores_legacy_toggle_keys(tmp_path):
    """ADR-0052/0053 evolution (2026-09-16): the [research] query_rewrite /
    rerank toggles were removed — config presence is the switch now. Old
    TOML files carrying the keys must still parse (keys are ignored)."""
    config_path = tmp_path / "config.toml"
    vault = tmp_path / "vault"
    vault.mkdir()
    service = CoreService(default_workspace=tmp_path / "runtime", config_path=config_path)
    service.init_config(valid_init_request(tmp_path / "runtime", vault))
    content = (
        config_path.read_text(encoding="utf-8")
        .replace(
            "inject_local_context = true",
            "inject_local_context = true\nquery_rewrite = true\nrerank = true",
        )
    )
    config_path.write_text(content, encoding="utf-8")

    loaded = load_user_config(config_path)

    assert not hasattr(loaded.research, "query_rewrite")
    assert not hasattr(loaded.research, "rerank")
    assert loaded.research.inject_local_context is True


def test_rerank_model_section_parses_when_present(tmp_path):
    config_path = tmp_path / "config.toml"
    vault = tmp_path / "vault"
    vault.mkdir()
    service = CoreService(default_workspace=tmp_path / "runtime", config_path=config_path)
    service.init_config(valid_init_request(tmp_path / "runtime", vault))
    content = config_path.read_text(encoding="utf-8") + (
        "\n[rerank_model]\n"
        'base_url = "https://rerank.example/v1"\n'
        'api_key = "rerank-key"\n'
        'model = "bge-reranker-v2-m3"\n'
    )
    config_path.write_text(content, encoding="utf-8")

    loaded = load_user_config(config_path)

    assert loaded.rerank_model is not None
    assert loaded.rerank_model.base_url == "https://rerank.example/v1"
    assert loaded.rerank_model.api_key == "rerank-key"
    assert loaded.rerank_model.model == "bge-reranker-v2-m3"


def test_rerank_model_section_absent_returns_none(tmp_path):
    config_path = tmp_path / "config.toml"
    vault = tmp_path / "vault"
    vault.mkdir()
    service = CoreService(default_workspace=tmp_path / "runtime", config_path=config_path)
    service.init_config(valid_init_request(tmp_path / "runtime", vault))

    loaded = load_user_config(config_path)

    assert loaded.rerank_model is None


def test_local_summarizer_slot_override_is_parsed(tmp_path):
    config_path = tmp_path / "config.toml"
    vault = tmp_path / "vault"
    vault.mkdir()
    service = CoreService(default_workspace=tmp_path / "runtime", config_path=config_path)
    service.init_config(valid_init_request(tmp_path / "runtime", vault))
    content = config_path.read_text(encoding="utf-8") + (
        "\n[chat_model.local_summarizer]\n"
        'model = "rewrite-model"\n'
    )
    config_path.write_text(content, encoding="utf-8")

    from research_agent.core.providers import build_role_chat_model_config

    loaded = load_user_config(config_path)
    resolved = build_role_chat_model_config(loaded, "local_summarizer")

    assert resolved.model == "rewrite-model"
    # Fields not overridden fall back to the global chat model.
    assert resolved.base_url == "https://models.example/v1"
