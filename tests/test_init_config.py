import os
import subprocess
import sys
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
    assert data["research"] == {"max_retrieval_rounds": 3, "max_concurrent_subtasks": 3}
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
        "message": "User config is missing. Run research-agent init first.",
    }


def test_malformed_existing_config_returns_config_invalid(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workspace]\nknowledge_base_path = \"D:/vault\"\n", encoding="utf-8")

    with pytest.raises(ResearchError) as exc_info:
        load_user_config(config_path)

    assert exc_info.value.code == "config_invalid"
    assert "Missing config field" in exc_info.value.message


def test_non_init_cli_commands_require_existing_config(tmp_path):
    env = os.environ.copy()
    env["RESEARCH_AGENT_CONFIG_PATH"] = str(tmp_path / "missing.toml")

    result = subprocess.run(
        [sys.executable, "-m", "research_agent.cli", "task", "list"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert "[config_missing] User config is missing. Run research-agent init first." in result.stdout


def test_cli_init_writes_config_without_provider_calls(tmp_path):
    config_path = tmp_path / "config.toml"
    workspace = tmp_path / "runtime"
    vault = tmp_path / "vault"
    vault.mkdir()
    env = os.environ.copy()
    env["RESEARCH_AGENT_CONFIG_PATH"] = str(config_path)
    env["RESEARCH_AGENT_PROVIDER_CALL_SENTINEL"] = "fail-if-read"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_agent.cli",
            "init",
            "--default-workspace",
            str(workspace),
            "--knowledge-base-path",
            str(vault),
            "--chat-base-url",
            "https://models.example/v1",
            "--chat-api-key",
            "chat-key",
            "--chat-model",
            "chat-model",
            "--embedding-base-url",
            "https://embeddings.example/v1",
            "--embedding-api-key",
            "embedding-key",
            "--embedding-model",
            "embedding-model",
            "--search-api-key",
            "search-key",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert "Config written:" in result.stdout
    assert config_path.exists()
    assert workspace.is_dir()


def test_cli_init_invalid_config_prints_research_error(tmp_path):
    config_path = tmp_path / "config.toml"
    workspace = tmp_path / "runtime"
    env = os.environ.copy()
    env["RESEARCH_AGENT_CONFIG_PATH"] = str(config_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_agent.cli",
            "init",
            "--default-workspace",
            str(workspace),
            "--knowledge-base-path",
            str(tmp_path / "missing-vault"),
            "--chat-base-url",
            "https://models.example/v1",
            "--chat-api-key",
            "chat-key",
            "--chat-model",
            "chat-model",
            "--embedding-base-url",
            "https://embeddings.example/v1",
            "--embedding-api-key",
            "embedding-key",
            "--embedding-model",
            "embedding-model",
            "--search-api-key",
            "search-key",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert "[config_invalid] Knowledge Base path must be an existing directory." in result.stdout
    assert not config_path.exists()
