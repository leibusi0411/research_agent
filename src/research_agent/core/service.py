from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Protocol

from research_agent.core.config import InitConfigRequest, UserConfig, init_user_config, load_user_config
from research_agent.core.deposit import deposit_web_report
from research_agent.core.errors import ResearchError
from research_agent.core.ids import generate_task_id

logger = logging.getLogger(__name__)
from research_agent.core.kb import KnowledgeBaseIndex
from research_agent.core.local_research import retrieve_local_chunks, run_local_research
from research_agent.core.providers import EmbeddingClient, OpenAICompatibleChatModel, OpenAICompatibleEmbeddingModel, build_chat_models, build_role_chat_model_config, ChatModelClient
from research_agent.core.tasks import TaskStore
from research_agent.core.workspace import Workspace, read_lock_task_id
from research_agent.web.provider_runtime import ProviderBackedWebResearchRuntime
from research_agent.web.schemas import PriorKnowledgeChunk
from research_agent.web.state_graph import RunnerConfig
from research_agent.web.tools import ToolGateway, ToolRunner, TavilySearchProvider, create_default_web_tool_registry


def build_local_retriever(
    *,
    config: UserConfig,
    config_path: str | Path | None,
    workspace: Workspace,
) -> Callable[[str], list[PriorKnowledgeChunk]] | None:
    """Build the Prior Knowledge retriever for Web Research (ADR-0046).

    Returns ``None`` when injection is disabled in config
    (``research.inject_local_context = false``) or when no usable Knowledge
    Base Index exists. Offline mode (``RESEARCH_AGENT_OFFLINE=1``) degrades
    to FTS5-only retrieval without an embedding client.
    """
    if not config.research.inject_local_context:
        return None
    status = KnowledgeBaseIndex(workspace, config_path).status()["status"]
    # "stale" is still usable: the FTS5 keyword index is available.
    if status not in ("ready", "stale"):
        return None
    embedding_client: EmbeddingClient | None = None
    if os.environ.get("RESEARCH_AGENT_OFFLINE") != "1":
        embedding_client = OpenAICompatibleEmbeddingModel.from_config(config.embedding_model)

    def retrieve(question: str) -> list[PriorKnowledgeChunk]:
        results = retrieve_local_chunks(
            sqlite_path=workspace.local_index_dir / "fts.sqlite",
            chroma_path=workspace.local_index_dir.parent / "chroma",
            question=question,
            embedding_client=embedding_client,
            top_k=5,
        )
        return [
            PriorKnowledgeChunk(
                text=result.get("text", ""),
                source_path=result.get("source_path", ""),
                heading_path=list(result.get("heading_path", [])),
            )
            for result in results
        ]

    return retrieve


def create_provider_runtime(
    config_path: str | Path | None,
    workspace_root: str,
    *,
    chat_models: dict[str, ChatModelClient] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    workspace_obj: Workspace | None = None,
    task_store: TaskStore | None = None,
    bus: Any | None = None,
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
    resolved_workspace = workspace_obj if workspace_obj is not None else Workspace(workspace_root)
    runner_config = RunnerConfig(
        workspace=workspace_root,
        chat_models=resolved_models,
        tool_gateway=tool_gateway,
        max_retrieval_rounds=config.research.max_retrieval_rounds,
        max_concurrent_subtasks=config.research.max_concurrent_subtasks,
        on_event=on_event,
        workspace_obj=workspace_obj,
        task_store=task_store,
        bus=bus,
        local_retriever=build_local_retriever(config=config, config_path=config_path, workspace=resolved_workspace),
    )
    return ProviderBackedWebResearchRuntime(config=runner_config)


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

    def run_local_research(self, question: str, *, task_id: str | None = None, embedding_client: EmbeddingClient | None = None, chat_model: ChatModelClient | None = None) -> dict:
        resolved_task_id = task_id or generate_task_id()
        offline = os.environ.get("RESEARCH_AGENT_OFFLINE") == "1"
        # Auto-create embedding client from config when none is provided, so
        # that ChromaDB vector search can supplement FTS5 keyword search.
        if embedding_client is None and self.config_path is not None and not offline:
            config = load_user_config(self.config_path)
            embedding_client = OpenAICompatibleEmbeddingModel.from_config(config.embedding_model)
        # Auto-create chat model from config for A+G summarization.
        # Uses the "curator" role model if configured, otherwise the default
        # chat_model — same resolution as web research roles.
        if chat_model is None and self.config_path is not None and not offline:
            config = load_user_config(self.config_path)
            chat_model = OpenAICompatibleChatModel.from_config(
                build_role_chat_model_config(config, "local_summarizer")
            )
        with self._active_family_lock("local", resolved_task_id):
            return self.run_local_research_unlocked(question, task_id=resolved_task_id, embedding_client=embedding_client, chat_model=chat_model)

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

    def run_local_research_unlocked(self, question: str, *, task_id: str, embedding_client: EmbeddingClient | None = None, chat_model: ChatModelClient | None = None) -> dict:
        return run_local_research(
            question=question,
            workspace=self.workspace,
            task_store=self.task_store,
            config_path=self.config_path,
            task_id=task_id,
            embedding_client=embedding_client,
            chat_model=chat_model,
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

    def list_finished_tasks(self) -> list[TaskRecord]:
        self.task_store.initialize()
        return self.task_store.list_finished_tasks()

    def deposit_web_report(self, task_id: str) -> dict[str, str]:
        """Knowledge Deposit: copy a completed Web Report File into the Markdown Vault."""
        return deposit_web_report(
            task_id=task_id,
            workspace=self.workspace,
            task_store=self.task_store,
            config_path=self.config_path,
        )

    def delete_finished_task(self, task_id: str) -> dict[str, Any]:
        # Fail-closed: if lock is unreadable, treat family as busy.
        for mode in ("local", "web"):
            lock_path = self.workspace.root / "locks" / f"{mode}.lock"
            if not lock_path.exists():
                continue
            lock_task_id = read_lock_task_id(lock_path)
            if lock_task_id == task_id:
                raise ResearchError(code="busy", message=f"Task is still running: {task_id}")
            if lock_task_id == "unknown":
                raise ResearchError(
                    code="busy",
                    message=f"{mode} lock file is unreadable — treat as busy for safety",
                )

        record = self.task_store.get_finished_task(task_id)
        if record is None:
            result_path = self.workspace.task_dir(task_id) / "result.json"
            if result_path.exists():
                try:
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise ResearchError(code="task_not_found", message="Task not found.") from exc
                if result.get("status") == "running":
                    raise ResearchError(code="busy", message=f"Task is still running: {task_id}")
            raise ResearchError(code="task_not_found", message="Task not found.")

        # Delete DB record first (authoritative removal).  File cleanup is
        # best-effort so a locked report file never leaves an orphaned DB row.
        self.task_store.delete_finished_task(task_id)

        cleanup_errors: list[str] = []
        try:
            self.workspace.delete_task_folder(task_id)
        except OSError as exc:
            cleanup_errors.append(f"task folder: {exc}")

        if not self._delete_report_file(record.report_path):
            # Only report an error when the path exists but could not be removed.
            report_path = record.report_path
            if report_path:
                path = Path(report_path)
                if not path.is_absolute():
                    path = self.workspace.root / path
                if path.exists():
                    cleanup_errors.append(f"report file: {report_path}")

        if cleanup_errors:
            logger.warning(
                "Post-delete cleanup incomplete for %s: %s",
                task_id,
                "; ".join(cleanup_errors),
            )

        return {"task_id": task_id, "deleted": True}

    def _delete_report_file(self, report_path: str | None) -> bool:
        if not report_path:
            return False
        path = Path(report_path)
        if not path.is_absolute():
            path = self.workspace.root / path
        resolved_report = path.resolve()
        reports_root = self.workspace.web_reports_dir.resolve()
        if reports_root != resolved_report and reports_root not in resolved_report.parents:
            raise OSError(f"report path escapes workspace reports directory: {report_path}")
        if not path.exists():
            return False
        path.unlink()
        return True

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
                active = read_lock_task_id(lock_path)
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


def _safe_future_result(future: Future, family: str) -> dict[str, Any]:
    try:
        return future.result()
    except Exception as exc:
        return {"mode": family, "status": "failed", "error": {"code": "runtime_error", "message": str(exc)}}


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
