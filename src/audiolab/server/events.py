"""WebSocket event hub shared by the job manager and model downloads."""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from typing import Any


class EventHub:
    def __init__(self, history: int = 300) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=history)
        self._lock = threading.Lock()

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.add(q)
            for event in self._history:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    break
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._history.append(event)
            subscribers = list(self._subscribers)
            loop = self._loop
        if not loop or not subscribers:
            return

        def _put() -> None:
            for q in subscribers:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass

        try:
            loop.call_soon_threadsafe(_put)
        except RuntimeError:
            pass


HUB = EventHub()
