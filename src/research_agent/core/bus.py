"""Per-instance event bus — asyncio-based pub/sub for SSE.

A shared ``Bus`` instance per FastAPI app, with ``publish`` / ``subscribe`` /
``subscribe_all`` primitives so SSE endpoints stream events without
file-polling fallback for live tasks.

Historical / completed tasks are served as plain JSON (see api/app.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

logger = logging.getLogger(__name__)


class Bus:
    """Per-app typed event bus with async-generator subscribers."""

    def __init__(self, *, queue_size: int = 1024) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._wildcard: list[asyncio.Queue[dict[str, Any]]] = []
        self._closed = False
        self._queue_size = queue_size
        # The ASGI event loop, captured on the first loop-side attach/subscribe.
        # ``publish_nowait`` runs on worker threads and must hop to this loop.
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # publish
    # ------------------------------------------------------------------

    async def publish(
        self,
        event_type: str,
        /,
        **properties: Any,
    ) -> None:
        """Push an event to every matching subscriber and wildcard."""
        if self._closed:
            return

        payload: dict[str, Any] = {"event": event_type, "data": json.dumps(properties, ensure_ascii=False)}

        # Typed subscribers — snapshot to tolerate mutation during iteration.
        for q in list(self._subscribers.get(event_type, [])):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("subscriber queue full, dropping event_type=%s", event_type)

        # Wildcard subscribers.
        for q in list(self._wildcard):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("wildcard queue full, dropping event_type=%s", event_type)

    def publish_nowait(
        self,
        event_type: str,
        /,
        **properties: Any,
    ) -> None:
        """Fire-and-forget publish — schedules :meth:`publish` on the app loop.

        Safe to call from a synchronous thread (e.g. ThreadPoolExecutor):
        the call hops to the loop captured by :meth:`attach`/:meth:`subscribe`.
        Without any subscriber yet (no loop captured, no loop on this thread)
        the event is only persisted by the caller, never streamed — drop it.
        """
        loop = self._loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.debug("publish_nowait dropped (no loop): event_type=%s", event_type)
                return

        try:
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(self.publish(event_type, **properties))
            )
        except RuntimeError:
            # Loop closed mid-shutdown (uvicorn reload / test teardown tail).
            logger.debug("publish_nowait dropped (loop closed): event_type=%s", event_type)

    @property
    def closed(self) -> bool:
        return self._closed

    def attach(self, event_type: str) -> asyncio.Queue[dict[str, Any]]:
        """Register and return a subscriber queue. Must be called on the loop thread.

        Captures the running loop so worker-thread publishers can hop over.
        Callers that replay persisted events should attach *before* replaying
        so nothing published during the replay is lost.
        """
        self._loop = asyncio.get_running_loop()
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.setdefault(event_type, []).append(q)
        logger.debug("attach event_type=%s", event_type)
        return q

    def detach(self, event_type: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a queue previously returned by :meth:`attach`."""
        with contextlib.suppress(ValueError):
            self._subscribers.get(event_type, []).remove(q)
        logger.debug("detach event_type=%s", event_type)

    # ------------------------------------------------------------------
    # subscribe
    # ------------------------------------------------------------------

    async def subscribe(self, event_type: str) -> AsyncGenerator[dict[str, Any], None]:
        """Async-generator yielding events of *event_type* as they arrive."""
        q = self.attach(event_type)
        try:
            while not self._closed:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield event
                except TimeoutError:
                    continue
        finally:
            self.detach(event_type, q)

    async def subscribe_all(self) -> AsyncGenerator[dict[str, Any], None]:
        """Async-generator yielding every published event."""
        self._loop = asyncio.get_running_loop()
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        self._wildcard.append(q)
        logger.debug("subscribe * (wildcard)")
        try:
            while not self._closed:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield event
                except TimeoutError:
                    continue
        finally:
            with contextlib.suppress(ValueError):
                self._wildcard.remove(q)
            logger.debug("unsubscribe * (wildcard)")

    # ------------------------------------------------------------------
    # shutdown
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Shut down the bus, unblocking all subscribers."""
        self._closed = True
        sentinel = {"event": "server.disposed", "data": "{}"}
        for q in list(self._wildcard):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(sentinel)
        for qs in list(self._subscribers.values()):
            for q in list(qs):
                with contextlib.suppress(asyncio.QueueFull):
                    q.put_nowait(sentinel)
