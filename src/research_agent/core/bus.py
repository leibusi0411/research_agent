"""Per-instance event bus — asyncio-based pub/sub for SSE.

Follows the pattern from ``G:\VSCode_project\mycode\mycode\bus\bus.py``:
a shared ``Bus`` instance per FastAPI app, with ``publish`` / ``subscribe`` /
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
        """Fire-and-forget publish — schedules :meth:`publish` on the running loop.

        Safe to call from a synchronous thread (e.g. ThreadPoolExecutor).
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no event loop (e.g. CLI tests)

        loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(self.publish(event_type, **properties))
        )

    # ------------------------------------------------------------------
    # subscribe
    # ------------------------------------------------------------------

    async def subscribe(self, event_type: str) -> AsyncGenerator[dict[str, Any], None]:
        """Async-generator yielding events of *event_type* as they arrive."""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        subs = self._subscribers.setdefault(event_type, [])
        subs.append(q)
        logger.debug("subscribe event_type=%s", event_type)
        try:
            while not self._closed:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield event
                except TimeoutError:
                    continue
        finally:
            with contextlib.suppress(ValueError):
                subs.remove(q)
            logger.debug("unsubscribe event_type=%s", event_type)

    async def subscribe_all(self) -> AsyncGenerator[dict[str, Any], None]:
        """Async-generator yielding every published event."""
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
