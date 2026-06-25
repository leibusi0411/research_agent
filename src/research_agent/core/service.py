from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Protocol

from research_agent.core.config import InitConfigRequest, init_user_config, load_user_config
from research_agent.core.errors import ResearchError
from research_agent.core.ids import generate_task_id
from research_agent.core.kb import KnowledgeBaseIndex
from research_agent.core.local_research import run_local_research
from research_agent.core.providers import EmbeddingClient, OpenAICompatibleChatModel, OpenAICompatibleEmbeddingModel, build_role_chat_model_config
from research_agent.core.tasks import TaskStore
from research_agent.core.workspace import Workspace
from research_agent.web.fake_runtime import FakeWebResearchRuntime
from research_agent.web.provider_runtime import ProviderBackedWebResearchRuntime
from research_agent.web.tools import ToolGateway, ToolRunner, TavilySearchProvider, create_default_web_tool_registry


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

    def run_local_research(self, question: str, *, task_id: str | None = None) -> dict:
        resolved_task_id = task_id or generate_task_id()
        with self._active_family_lock("local", resolved_task_id):
            return self.run_local_research_unlocked(question, task_id=resolved_task_id)

    def run_web_research(self, question: str, *, runtime: WebResearchRuntime | None = None, chat_model: object | None = None, task_id: str | None = None) -> dict:
        resolved_task_id = task_id or generate_task_id()
        resolved_runtime = runtime
        if resolved_runtime is None:
            config = load_user_config(self.config_path)
            resolved_model = chat_model
            if resolved_model is None:
                resolved_model = OpenAICompatibleChatModel.from_config(build_role_chat_model_config(config, "planner"))
            search_provider = TavilySearchProvider(api_key=config.search.api_key)
            tool_runner = ToolRunner(config=config.web_tools, search_provider=search_provider)
            tool_gateway = ToolGateway(registry=create_default_web_tool_registry(), runner=tool_runner)
            resolved_runtime = ProviderBackedWebResearchRuntime(
                workspace=str(self.workspace.root),
                chat_model=resolved_model,
                tool_gateway=tool_gateway,
                max_retrieval_rounds=config.research.max_retrieval_rounds,
                max_concurrent_subtasks=config.research.max_concurrent_subtasks,
            )
        with self._active_family_lock("web", resolved_task_id):
            return self.run_web_research_unlocked(question, runtime=resolved_runtime, task_id=resolved_task_id)

    def run_local_research_unlocked(self, question: str, *, task_id: str) -> dict:
        return run_local_research(
            question=question,
            workspace=self.workspace,
            task_store=self.task_store,
            config_path=self.config_path,
            task_id=task_id,
        )

    def run_web_research_unlocked(self, question: str, *, runtime: WebResearchRuntime, task_id: str) -> dict:
        return runtime.run(question, task_id=task_id)

    def run_both(self, question: str, *, web_runtime: WebResearchRuntime | None = None) -> dict:
        with ThreadPoolExecutor(max_workers=2) as executor:
            local_future = executor.submit(self._run_family_result, "local", question, None)
            web_future = executor.submit(self._run_family_result, "web", question, web_runtime)
            local_result = _safe_future_result(local_future, "local")
            web_result = _safe_future_result(web_future, "web")
        return {
            "status": "completed" if local_result["status"] == "completed" and web_result["status"] == "completed" else "failed",
            "local": local_result,
            "web": web_result,
        }

    def list_finished_tasks(self):
        self.task_store.initialize()
        return self.task_store.list_finished_tasks()

    def get_kb_status(self) -> dict:
        return KnowledgeBaseIndex(self.workspace, self.config_path).status()

    def rebuild_kb_index(self, *, embedding_client: EmbeddingClient | None = None) -> dict:
        if embedding_client is None:
            if os.environ.get("RESEARCH_AGENT_FAKE_EMBEDDINGS") == "1":
                embedding_client = _DeterministicEmbeddingClient()
            else:
                config = load_user_config(self.config_path)
                embedding_client = OpenAICompatibleEmbeddingModel.from_config(config.embedding_model)
        return KnowledgeBaseIndex(self.workspace, self.config_path, embedding_client=embedding_client).rebuild()

    def _run_family_result(self, family: str, question: str, web_runtime: WebResearchRuntime | None) -> dict:
        try:
            if family == "local":
                return self.run_local_research(question)
            if family == "web":
                return self.run_web_research(question, runtime=web_runtime)
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
        except FileExistsError as exc:
            active = _read_lock(lock_path)
            raise ResearchError(
                code="busy",
                message=f"{family} task family is already active: {active}",
            ) from exc
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"task_id": task_id}, handle)
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


class _DeterministicEmbeddingClient:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _text in texts]
