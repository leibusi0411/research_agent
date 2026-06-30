from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)

# R-75: Runner registry for SSE EventStream lookup.
# Maps task_id -> ProviderBackedWebResearchRuntime so the SSE endpoint
# can access runtime.runner.events() when available, falling back to
# events.jsonl polling for tasks that started before the upgrade or
# whose runner hasn't been created yet.
_active_runtimes: dict[str, Any] = {}

from research_agent.core.config import InitConfigRequest, UserConfig, default_config_path, load_user_config
from research_agent.core.errors import ResearchError
from research_agent.core.ids import generate_task_id, utc_now_iso, validate_task_id
from research_agent.core.providers import EmbeddingClient
from research_agent.core.service import CoreService, create_provider_runtime
from research_agent.web.provider_runtime import ProviderBackedWebResearchRuntime


WebRuntimeFactory = Callable[[str], Any]
EmbeddingClientFactory = Callable[[UserConfig], EmbeddingClient]


def create_app(
    *,
    config_path: str | Path | None = None,
    web_runtime_factory: WebRuntimeFactory | None = None,
    embedding_client_factory: EmbeddingClientFactory | None = None,
) -> FastAPI:
    resolved_config_path = Path(config_path) if config_path is not None else default_config_path()
    executor = ThreadPoolExecutor(max_workers=4)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        executor.shutdown(wait=True)

    app = FastAPI(title="Research Agent", lifespan=lifespan)

    _cached_service: CoreService | None = None

    def service() -> CoreService:
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

    @app.post("/api/research/local")
    def start_local(payload: dict[str, Any]) -> JSONResponse:
        task_id = generate_task_id()
        question = _question(payload)
        current_service = service()
        lock = current_service.acquire_family_lock("local", task_id)
        lock.__enter__()
        try:
            _create_running_task(current_service, task_id=task_id, mode="local", question=question)
            executor.submit(lambda: _run_background(lock, lambda: current_service.run_local_research_unlocked(question, task_id=task_id)))
        except Exception:
            lock.__exit__(None, None, None)
            raise
        return JSONResponse({"task_id": task_id, "mode": "local", "status": "running", "question": question}, status_code=202)

    @app.post("/api/research/web")
    def start_web(payload: dict[str, Any]) -> JSONResponse:
        current_service = service()
        runtime = web_runtime_factory(str(current_service.workspace.root)) if web_runtime_factory is not None else None
        task_id = generate_task_id()
        question = _question(payload)
        if runtime is None:
            # Use CoreService's default provider-backed runtime construction when no test/runtime override is supplied.
            runtime = _default_web_runtime(current_service)
        _active_runtimes[task_id] = runtime
        lock = current_service.acquire_family_lock("web", task_id)
        lock.__enter__()
        try:
            _create_running_task(current_service, task_id=task_id, mode="web", question=question)
            executor.submit(lambda: _cleanup_background(lock, task_id, lambda: current_service.run_web_research_unlocked(question, runtime=runtime, task_id=task_id)))
        except Exception:
            lock.__exit__(None, None, None)
            raise
        return JSONResponse({"task_id": task_id, "mode": "web", "status": "running", "question": question}, status_code=202)

    @app.get("/api/tasks/active")
    def active_tasks() -> dict[str, Any]:
        current_service = service()
        active = []
        for mode in ["local", "web"]:
            lock_path = current_service.workspace.root / "locks" / f"{mode}.lock"
            if lock_path.exists():
                active.append({"mode": mode, "task_id": _read_lock_task_id(lock_path)})
        return {"active": active}

    @app.get("/api/tasks/finished")
    def finished_tasks() -> dict[str, Any]:
        records = service().list_finished_tasks()
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
    async def task_events(task_id: str) -> StreamingResponse:
        _validate_task_id_as_research_error(task_id)
        events_path = service().workspace.task_dir(task_id) / "events.jsonl"
        runtime = _active_runtimes.get(task_id)
        return StreamingResponse(
            _stream_events(events_path, runtime.runner if runtime is not None else None),
            media_type="text/event-stream",
        )

    @app.get("/api/tasks/{task_id}/result")
    def task_result(task_id: str) -> JSONResponse:
        _validate_task_id_as_research_error(task_id)
        result_path = service().workspace.task_dir(task_id) / "result.json"
        if not result_path.exists():
            return _error_response(ResearchError(code="runtime_error", message="Task result not found."), status_code=404)
        return JSONResponse(json.loads(result_path.read_text(encoding="utf-8")))

    @app.get("/api/kb/status")
    def kb_status() -> JSONResponse:
        try:
            return JSONResponse(service().get_kb_status())
        except ResearchError as error:
            return _error_response(error)

    @app.post("/api/kb/rebuild")
    def kb_rebuild() -> JSONResponse:
        current_service = service()
        embedding_client = None
        if embedding_client_factory is not None:
            embedding_client = embedding_client_factory(load_user_config(resolved_config_path))
        result = current_service.rebuild_kb_index(embedding_client=embedding_client)
        return JSONResponse(result, status_code=200 if "error" not in result else 400)

    return app


def _question(payload: dict[str, Any]) -> str:
    question = str(payload.get("question", "")).strip()
    if not question:
        raise ResearchError(code="config_invalid", message="question is required.")
    return question


def _error_response(error: ResearchError, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"error": error.to_dict()}, status_code=status_code)


def _read_lock_task_id(lock_path: Path) -> str:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        return str(payload.get("task_id") or "unknown")
    except Exception:
        return "unknown"


async def _stream_events(events_path: Path, runner=None):
    """Stream task progress events as SSE.

    When a live runner is available, iterates its EventStream (janus.Queue
    backed AsyncIterator) for real-time delivery.  Falls back to polling
    events.jsonl otherwise (e.g. historical tasks or tasks whose runner
    hasn't started yet).
    """
    if runner is not None:
        # EventStream path — real-time, no polling
        async for event in runner.events():
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        return

    # Fallback: poll events.jsonl every 100 ms
    deadline = time.time() + 1800  # 30 minutes max
    offset = 0
    while time.time() < deadline:
        if events_path.exists():
            text = events_path.read_text(encoding="utf-8")
            if len(text) > offset:
                chunk = text[offset:]
                offset = len(text)
                for line in chunk.splitlines():
                    if line.strip():
                        yield f"data: {line}\n\n"
            result_path = events_path.with_name("result.json")
            if _is_terminal_result(result_path):
                break
        time.sleep(0.1)
    else:
        yield f'data: {json.dumps({"event_type": "stream_timeout", "message": "SSE stream timed out."})}\n\n'


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


def _run_background(lock, operation) -> None:
    try:
        operation()
    except Exception as exc:
        logger.exception("Background task failed: %s", exc)
    finally:
        lock.__exit__(None, None, None)


def _cleanup_background(lock, task_id: str, operation) -> None:
    """Run background operation then clean up the runner registry entry."""
    try:
        operation()
    except Exception as exc:
        logger.exception("Background task failed: %s", exc)
    finally:
        lock.__exit__(None, None, None)
        _active_runtimes.pop(task_id, None)


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
    layer pushes events through SSE (``_stream_events`` polls ``events.jsonl``),
    not through the in-process callback.  CLI callers that need live progress
    pass ``on_event`` via ``CoreService.run_web_research(on_event=...)``.
    """
    return create_provider_runtime(service.config_path, str(service.workspace.root))
