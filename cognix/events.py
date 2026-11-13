"""A tiny thread-safe publish/subscribe bus between the assistant and the UI."""

from __future__ import annotations

import queue
import threading


class EventBus:
    def __init__(self):
        self._subscribers: set = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=2000)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def emit(self, kind: str, **data) -> None:
        event = {"type": kind, **data}
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # a stalled client; it resyncs from /api/state when it reconnects
