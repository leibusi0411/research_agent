from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Protocol

from research_agent.core.config import InitConfigRequest, init_user_config, load_user_config
from research_agent.core.errors import ResearchError
from research_agent.core.ids import generate_task_id
from research_agent.core.kb import KnowledgeBaseIndex
from research_agent.core.local_research import run_local_research
from research_agent.core.providers import EmbeddingClient, OpenAICompatibleChatModel, OpenAICompatibleEmbeddingModel, build_chat_models, ChatModelClient
from research_agent.core.tasks import TaskStore
from research_agent.core.workspace import Workspace
from research_agent.web.provider_runtime import ProviderBackedWebResearchRuntime
from research_agent.web.tools import ToolGateway, ToolRunner, TavilySearchProvider, create_default_web_tool_registry


def create_provider_runtime(
    config_path: str | Path | None,
    workspace_root: str,
    *,
    chat_models: dict[str, ChatModelClient] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    workspace_obj: Workspace | None = None,
    task_store: TaskStore | None = None,
) -> ProviderBackedWebResearchRuntime:
    """Shared factory for ProviderBackedWebResearchRuntime.

    Used by both ``CoreService.run_web_research`` and the API layer's
    ``_default_web_runtime`` to avoid duplication (fixes R-20, R-44).

    Accepts optional ``workspace_obj`` and ``task_store`` to reduce
    duplicate Workspace instances in the call chain (fixes R-24).
    """
    config = load_user_config(config_path)
    resolved_models = chat_models
    if resolved_models is None:
        resolved_models = build_chat_models(config)
    search_provider = TavilySearchProvider(api_key=config.search.api_key)
    tool_runner = ToolRunner(config=config.web_tools, search_provider=search_provider)
    tool_gateway = ToolGateway(registry=create_default_web_tool_registry(), runner=tool_runner)
    return ProviderBackedWebResearchRuntime(
        workspace=workspace_root,
        chat_models=resolved_models,
        tool_gateway=tool_gateway,
        max_retrieval_rounds=config.research.max_retrieval_rounds,
        max_concurrent_subtasks=config.research.max_concurrent_subtasks,
        on_event=on_event,
        workspace_obj=workspace_obj,
        task_store=task_store,
    )


class WebResearchRuntime(Protocol):
    """Protocol for web research runtime implementations."""
    def run(self, question: str, task_id: str | None = None) -> dict:
        ...


class CoreService:
    def __init__(self, default_workspace: str | Path, config_path: str | Path | None = None) -> None:
        self.workspace = Workspace(default_workspace)
        self.task_store = TaskStore(self.workspace.root / "tasks.sqlite")
        self.config_path = Path(config_path) if config_path is not None else None

    def init_config(self, request: InitConfigRequest, launch_cwd: Path | None = None) -> Path:
        config_path = init_user_config(request, config_path=self.config_path, launch_cwd=launch_cwd)
        config = load_user_config(config_path)
        self.workspace = Workspace(config.workspace.default_workspace)
        self.task_store = TaskStore(self.workspace.root / "tasks.sqlite")
        self.workspace.ensure()
        return config_path

    def run_local_research(self, question: str, *, task_id: str | None = None, embedding_client: EmbeddingClient | None = None) -> dict:
        resolved_task_id = task_id or generate_task_id()
        with self._active_family_lock("local", resolved_task_id):
            return self.run_local_research_unlocked(question, task_id=resolved_task_id, embedding_client=embedding_client)

    def run_web_research(self, question: str, *, runtime: WebResearchRuntime | None = None, chat_models: dict[str, ChatModelClient] | None = None, task_id: str | None = None, on_event: Callable[[dict[str, Any]], None] | None = None) -> dict:
        resolved_task_id = task_id or generate_task_id()
        resolved_runtime = runtime
        if resolved_runtime is None:
            resolved_runtime = create_provider_runtime(
                self.config_path,
                str(self.workspace.root),
                chat_models=chat_models,
                on_event=on_event,
                workspace_obj=self.workspace,
                task_store=self.task_store,
            )
        elif on_event is not None:
            # R-33: When a custom runtime is supplied, still forward on_event if
            # the runtime supports it (has a settable on_event attribute).
            if hasattr(resolved_runtime, "on_event"):
                resolved_runtime.on_event = on_event  # type: ignore[union-attr]
        with self._active_family_lock("web", resolved_task_id):
            return self.run_web_research_unlocked(question, runtime=resolved_runtime, task_id=resolved_task_id)

    def run_local_research_unlocked(self, question: str, *, task_id: str, embedding_client: EmbeddingClient | None = None) -> dict:
        return run_local_research(
            question=question,
            workspace=self.workspace,
            task_store=self.task_store,
            config_path=self.config_path,
            task_id=task_id,
            embedding_client=embedding_client,
        )

    def run_web_research_unlocked(self, question: str, *, runtime: WebResearchRuntime, task_id: str) -> dict:
        return runtime.run(question, task_id=task_id)

    def run_both(self, question: str, *, web_runtime: WebResearchRuntime | None = None, on_event: Callable[[dict[str, Any]], None] | None = None) -> dict:
        with ThreadPoolExecutor(max_workers=2) as executor:
            local_future = executor.submit(self._run_family_result, "local", question, None, None)
            web_future = executor.submit(self._run_family_result, "web", question, web_runtime, on_event)
            local_result = _safe_future_result(local_future, "local")
            web_result = _safe_future_result(web_future, "web")
        local_ok = local_result.get("status") == "completed"
        web_ok = web_result.get("status") == "completed"
        if local_ok and web_ok:
            overall = "completed"
        elif local_ok or web_ok:
            overall = "partial"
        else:
            overall = "failed"
        return {
            "status": overall,
            "local": local_result,
            "web": web_result,
        }

    def list_finished_tasks(self):
        self.task_store.initialize()
        return self.task_store.list_finished_tasks()

    def get_kb_status(self) -> dict:
        return KnowledgeBaseIndex(self.workspace, self.config_path).status()

    def rebuild_kb_index(self, *, embedding_client: EmbeddingClient | None = None) -> dict:
        """Rebuild the Knowledge Base index.

        Args:
            embedding_client: Optional embedding model client.  When **None**
                (the default), a real embedding client is created from the
                user config.  Pass an explicit ``EmbeddingClient`` to use a
                custom or test embedding provider.  Pass a *sentinel* (e.g.
                ``False``) is not supported — if you want no embedding, pass
                a mock client that returns empty vectors.
        """
        if embedding_client is None:
            config = load_user_config(self.config_path)
            embedding_client = OpenAICompatibleEmbeddingModel.from_config(config.embedding_model)
        return KnowledgeBaseIndex(self.workspace, self.config_path, embedding_client=embedding_client).rebuild()

    def _run_family_result(self, family: str, question: str, web_runtime: WebResearchRuntime | None, on_event: Callable[[dict[str, Any]], None] | None) -> dict:
        try:
            if family == "local":
                return self.run_local_research(question)
            if family == "web":
                return self.run_web_research(question, runtime=web_runtime, on_event=on_event)
        except ResearchError as error:
            return {"mode": family, "status": "failed", "error": error.to_dict()}
        raise ValueError(f"unknown task family: {family}")

    @contextmanager
    def _active_family_lock(self, family: str, task_id: str) -> Iterator[None]:
        lock_dir = self.workspace.root / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / f"{family}.lock"
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # Check for stale lock (process crash leaves orphaned lock file)
            if _is_lock_stale(lock_path):
                lock_path.unlink(missing_ok=True)
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            else:
                active = _read_lock(lock_path)
                raise ResearchError(
                    code="busy",
                    message=f"{family} task family is already active: {active}",
                )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"task_id": task_id, "pid": os.getpid()}, handle)
            yield
        finally:
            lock_path.unlink(missing_ok=True)

    def acquire_family_lock(self, family: str, task_id: str):
        return self._active_family_lock(family, task_id)


def _safe_future_result(future, family: str) -> dict:
    try:
        return future.result()
    except Exception as exc:
        return {"mode": family, "status": "failed", "error": {"code": "runtime_error", "message": str(exc)}}


def _read_lock(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return str(payload.get("task_id") or "unknown")
    except Exception:
        return "unknown"


def _is_lock_stale(path: Path, timeout_seconds: int = 3600) -> bool:
    """Return True if the lock file is older than timeout (default 1 hour).

    Used to auto-recover from orphaned lock files after a process crash.
    Also checks PID liveness on platforms where os.kill(pid, 0) works.
    """
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return True  # Can't stat → assume stale

    if time.time() - mtime > timeout_seconds:
        return True

    # Best-effort PID check on POSIX (signal 0 = existence check only)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        pid = payload.get("pid")
        if pid is not None and hasattr(os, "kill"):
            os.kill(int(pid), 0)
            return False  # PID exists → lock still valid
    except OSError:
        return True  # PID doesn't exist → stale
    except (ValueError, json.JSONDecodeError):
        return True

    return False
