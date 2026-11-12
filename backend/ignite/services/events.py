"""In-process event bus for SSE.

Analysis jobs and execution run in worker threads, so publishing has to hop
back onto the event loop. A slow browser never blocks the worker: queues are
bounded and drops are counted.
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from typing import Any

from backend.ignite.store.db import utc_now


class EventBus:
    def __init__(self, history: int = 200) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._history: deque[dict[str, Any]] = deque(maxlen=history)
        self.dropped = 0

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def publish(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        event = {"type": event_type, "ts": utc_now(), **(data or {})}
        self._history.append(event)

        loop = self._loop
        if loop is None or not loop.is_running():
            return

        def _deliver() -> None:
            with self._lock:
                queues = list(self._subscribers)
            for queue in queues:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    self.dropped += 1

        loop.call_soon_threadsafe(_deliver)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._history)[-limit:]
