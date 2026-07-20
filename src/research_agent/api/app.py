from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

# R-75: Runner registry for SSE EventStream lookup.
# Maps task_id -> ProviderBackedWebResearchRuntime so the SSE endpoint
# can access runtime.runner.events() when available, falling back to
# events.jsonl polling for tasks that started before the upgrade or
# whose runner hasn't been created yet.
_active_runtimes: dict[str, Any] = {}

from research_agent.core.bus import Bus
from research_agent.core.config import InitConfigRequest, UserConfig, default_config_path, load_user_config
from research_agent.core.errors import ResearchError
from research_agent.core.ids import generate_task_id, utc_now_iso, validate_task_id
from research_agent.core.providers import EmbeddingClient
from research_agent.core.service import CoreService, create_provider_runtime
from research_agent.core.workspace import read_lock_task_id
from research_agent.web.provider_runtime import ProviderBackedWebResearchRuntime


WebRuntimeFactory = Callable[[str], Any]
EmbeddingClientFactory = Callable[[UserConfig], EmbeddingClient]


def create_app(
    *,
    config_path: str | Path | None = None,
    web_runtime_factory: WebRuntimeFactory | None = None,
    embedding_client_factory: EmbeddingClientFactory | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Route registration is delegated to focused helper functions to keep
    this factory small and readable (R-102).
    """
    resolved_config_path = Path(config_path) if config_path is not None else default_config_path()
    executor = ThreadPoolExecutor(max_workers=4)
    bus = Bus()  # SSE event bus shared across all tasks

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        executor.shutdown(wait=True)

    app = FastAPI(title="Research Agent", lifespan=lifespan)

    _cached_service: CoreService | None = None

    def get_service() -> CoreService:
        """Return a cached CoreService instance (fixes R-71).

        The instance is created once and reused across requests so that
        config is loaded only once per process lifetime.
        """
        nonlocal _cached_service
        if _cached_service is not None:
            return _cached_service
        try:
            config = load_user_config(resolved_config_path)
            _cached_service = CoreService(default_workspace=config.workspace.default_workspace, config_path=resolved_config_path)
        except ResearchError:
            _cached_service = CoreService(default_workspace=Path.cwd() / ".research_agent", config_path=resolved_config_path)
        return _cached_service

    @app.exception_handler(ResearchError)
    async def research_error_handler(_request, exc: ResearchError):
        return _error_response(exc)

    _register_setup_routes(app, resolved_config_path)
    _register_research_routes(app, get_service, executor, web_runtime_factory)
    _register_task_routes(app, get_service)
    _register_kb_routes(app, get_service, resolved_config_path, embedding_client_factory)

    return app


# ── route registration helpers ────────────────────────────────────────


def _register_setup_routes(app: FastAPI, resolved_config_path: Path) -> None:
    """Register /api/setup/* routes."""

    @app.get("/api/setup/status")
    def setup_status() -> dict[str, Any]:
        try:
            config = load_user_config(resolved_config_path)
        except ResearchError:
            return {"configured": False}
        return {"configured": True, "config_path": str(resolved_config_path), "workspace": str(config.workspace.default_workspace)}

    @app.post("/api/setup/init")
    def setup_init(payload: dict[str, Any]) -> dict[str, Any]:
        request = InitConfigRequest(
            default_workspace=Path(payload["default_workspace"]),
            knowledge_base_path=Path(payload["knowledge_base_path"]),
            chat_base_url=str(payload["chat_base_url"]),
            chat_api_key=str(payload["chat_api_key"]),
            chat_model=str(payload["chat_model"]),
            embedding_base_url=str(payload["embedding_base_url"]),
            embedding_api_key=str(payload["embedding_api_key"]),
            embedding_model=str(payload["embedding_model"]),
            search_api_key=str(payload["search_api_key"]),
        )
        written = CoreService(default_workspace=request.default_workspace, config_path=resolved_config_path).init_config(request)
        return {"configured": True, "config_path": str(written)}


def _register_research_routes(
    app: FastAPI,
    get_service: Callable[[], CoreService],
    executor: ThreadPoolExecutor,
    web_runtime_factory: WebRuntimeFactory | None,
) -> None:
    """Register /api/research/* routes."""

    @app.post("/api/research/local")
    def start_local(payload: dict[str, Any]) -> JSONResponse:
        task_id = generate_task_id()
        question = _question(payload)
        current_service = get_service()
        _create_running_task(current_service, task_id=task_id, mode="local", question=question)
        _submit_background_task(
            executor,
            current_service.acquire_family_lock("local", task_id),
            lambda: current_service.run_local_research_unlocked(question, task_id=task_id),
        )
        return JSONResponse({"task_id": task_id, "mode": "local", "status": "running", "question": question}, status_code=202)

    @app.post("/api/research/web")
    def start_web(payload: dict[str, Any]) -> JSONResponse:
        current_service = get_service()
        runtime = web_runtime_factory(str(current_service.workspace.root)) if web_runtime_factory is not None else None
        task_id = generate_task_id()
        question = _question(payload)
        if runtime is None:
            runtime = _default_web_runtime(current_service)
        _active_runtimes[task_id] = runtime
        _create_running_task(current_service, task_id=task_id, mode="web", question=question)
        _submit_background_task(
            executor,
            current_service.acquire_family_lock("web", task_id),
            lambda: current_service.run_web_research_unlocked(question, runtime=runtime, task_id=task_id),
            task_id=task_id,
        )
        return JSONResponse({"task_id": task_id, "mode": "web", "status": "running", "question": question}, status_code=202)


def _register_task_routes(app: FastAPI, get_service: Callable[[], CoreService]) -> None:
    """Register /api/tasks/* routes."""

    @app.get("/api/tasks/active")
    def active_tasks() -> dict[str, Any]:
        current_service = get_service()
        active = []
        for mode in ["local", "web"]:
            lock_path = current_service.workspace.root / "locks" / f"{mode}.lock"
            if lock_path.exists():
                active.append({"mode": mode, "task_id": read_lock_task_id(lock_path)})
        return {"active": active}

    @app.get("/api/tasks/finished")
    def finished_tasks() -> dict[str, Any]:
        records = get_service().list_finished_tasks()
        return {
            "tasks": [
                {
                    "task_id": record.task_id,
                    "mode": record.mode,
                    "status": record.status,
                    "title_or_question": record.title_or_question,
                    "created_at": record.created_at,
                }
                for record in records
            ]
        }

    @app.get("/api/tasks/{task_id}/events")
    async def task_events(task_id: str):
        _validate_task_id_as_research_error(task_id)
        events_path = get_service().workspace.task_dir(task_id) / "events.jsonl"
        runtime = _active_runtimes.get(task_id)
        runner = getattr(runtime, "runner", None) if runtime is not None else None

        # Historical / completed task (no active runtime at all):
        # return full events list as JSON — no need for SSE streaming.
        if runtime is None:
            result_path = events_path.with_name("result.json")
            if _is_terminal_result(result_path):
                events: list[dict[str, Any]] = []
                if events_path.exists():
                    for line in events_path.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            try:
                                events.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
                return JSONResponse(events)

        # Live task: stream via Bus + EventSourceResponse (mycode pattern).
        if runner is not None and hasattr(runner, "events"):
            return EventSourceResponse(runner.events())

        # Task registered but runner not ready yet: poll fallback.
        return EventSourceResponse(_stream_events(events_path))

    @app.get("/api/tasks/{task_id}/result")
    def task_result(task_id: str) -> JSONResponse:
        _validate_task_id_as_research_error(task_id)
        result_path = get_service().workspace.task_dir(task_id) / "result.json"
        if not result_path.exists():
            return _error_response(ResearchError(code="runtime_error", message="Task result not found."), status_code=404)
        return JSONResponse(json.loads(result_path.read_text(encoding="utf-8")))

    @app.delete("/api/tasks/{task_id}")
    def delete_task(task_id: str) -> JSONResponse:
        _validate_task_id_as_research_error(task_id)
        try:
            return JSONResponse(get_service().delete_finished_task(task_id))
        except ResearchError as error:
            status_code = 409 if error.code == "busy" else 404 if error.code == "task_not_found" else 400
            return _error_response(error, status_code=status_code)


def _register_kb_routes(
    app: FastAPI,
    get_service: Callable[[], CoreService],
    resolved_config_path: Path,
    embedding_client_factory: EmbeddingClientFactory | None,
) -> None:
    """Register /api/kb/* routes."""

    @app.get("/api/kb/status")
    def kb_status() -> JSONResponse:
        try:
            return JSONResponse(get_service().get_kb_status())
        except ResearchError as error:
            return _error_response(error)

    @app.post("/api/kb/rebuild")
    def kb_rebuild() -> JSONResponse:
        current_service = get_service()
        embedding_client = None
        if embedding_client_factory is not None:
            embedding_client = embedding_client_factory(load_user_config(resolved_config_path))
        result = current_service.rebuild_kb_index(embedding_client=embedding_client)
        # Normalise core-layer plain-string errors to the structured API format
        # so the frontend sees a consistent {code, message} object (R-131).
        if isinstance(result.get("error"), str):
            result["error"] = {"code": "kb_rebuild_error", "message": result["error"]}
        return JSONResponse(result, status_code=200 if "error" not in result else 400)


def _question(payload: dict[str, Any]) -> str:
    question = str(payload.get("question", "")).strip()
    if not question:
        raise ResearchError(code="config_invalid", message="question is required.")
    return question


def _error_response(error: ResearchError, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"error": error.to_dict()}, status_code=status_code)


async def _stream_events(events_path: Path):
    """Fallback SSE: poll events.jsonl every 100 ms with incremental reads.

    Only used when a task is registered in ``_active_runtimes`` but its
    runner hasn't started yet.  Once the runner is ready the caller
    switches to ``runner.events()`` backed by the Bus.
    """
    deadline = time.time() + 1800  # 30 minutes max
    offset = 0
    while time.time() < deadline:
        if events_path.exists():
            with open(events_path, "r", encoding="utf-8") as f:
                f.seek(offset)
                chunk = f.read()
                if chunk:
                    offset = f.tell()
                    for line in chunk.splitlines():
                        if line.strip():
                            yield {"data": line}
            result_path = events_path.with_name("result.json")
            if _is_terminal_result(result_path):
                break
        elif not events_path.parent.exists():
            break
        await asyncio.sleep(0.1)
    else:
        yield {
            "data": json.dumps({"event_type": "stream_timeout", "message": "SSE stream timed out."}),
        }


def _validate_task_id_as_research_error(task_id: str) -> None:
    try:
        validate_task_id(task_id)
    except ValueError as exc:
        raise ResearchError(code="config_invalid", message=str(exc)) from exc


def _create_running_task(service: CoreService, *, task_id: str, mode: str, question: str) -> None:
    created_at = utc_now_iso()
    service.workspace.create_task_folder(
        task_id,
        task_metadata={"task_id": task_id, "mode": mode, "question": question, "created_at": created_at},
        result={"task_id": task_id, "mode": mode, "question": question, "status": "running", "created_at": created_at},
    )
    service.workspace.append_event(
        task_id,
        {
            "task_id": task_id,
            "mode": mode,
            "phase": "local_rag" if mode == "local" else "web_planning",
            "event_type": "started",
            "created_at": utc_now_iso(),
            "message": "Task started.",
            "details": {"items": []},
        },
    )


def _run_background(lock: Any, operation: Callable[[], Any]) -> None:
    """Run *operation* in background and release *lock* when done (R-110, R-114).

    The lock is acquired in the main thread before this is submitted to the
    executor; this function releases it in the background thread after the
    operation completes (or fails).
    """
    try:
        operation()
    except Exception as exc:
        logger.exception("Background task failed: %s", exc)
    finally:
        lock.__exit__(None, None, None)


def _cleanup_background(lock: Any, task_id: str, operation: Callable[[], Any]) -> None:
    """Run *operation* in background, release *lock*, and remove runner from
    registry when done (R-111, R-114).

    Same lock lifecycle as :func:`_run_background` but additionally cleans
    up the ``_active_runtimes`` entry for *task_id*.
    """
    try:
        operation()
    except Exception as exc:
        logger.exception("Background task failed: %s", exc)
    finally:
        lock.__exit__(None, None, None)
        _active_runtimes.pop(task_id, None)


def _submit_background_task(
    executor: ThreadPoolExecutor,
    lock: Any,
    operation: Callable[[], Any],
    *,
    task_id: str | None = None,
) -> None:
    """Acquire *lock* in the current thread and submit *operation* to the
    executor, ensuring the lock is released in the background thread after
    the operation completes (R-114).

    When *task_id* is provided the runner registry is also cleaned up.
    """
    lock.__enter__()
    try:
        if task_id is not None:
            executor.submit(lambda: _cleanup_background(lock, task_id, operation))
        else:
            executor.submit(lambda: _run_background(lock, operation))
    except Exception:
        lock.__exit__(None, None, None)
        raise


def _is_terminal_result(result_path: Path) -> bool:
    if not result_path.exists():
        return False
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        return payload.get("status") in {"completed", "failed"}
    except Exception:
        return False


def _default_web_runtime(service: CoreService) -> ProviderBackedWebResearchRuntime:
    """Create a provider-backed runtime using the shared factory (fixes R-20, R-44).

    The ``on_event`` callback is intentionally omitted here because the API
    layer pushes events through SSE via the Bus.  CLI callers that need
    live progress pass ``on_event`` via ``CoreService.run_web_research(on_event=...)``.
    """
    return create_provider_runtime(service.config_path, str(service.workspace.root), bus=bus)
