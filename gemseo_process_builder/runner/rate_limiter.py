"""Limit the number of events per second (SPEC § 11.3).

Up to ``limit`` events of each type are sent per second; the others are kept
and sent together, as one ``batch`` event, when the next second starts (or on
``flush``). Events sharing a key replace each other while they wait: only the
latest state of a node is worth showing.
"""

import threading
import time
from collections.abc import Callable
from typing import Any

Send = Callable[[str, Any], None]

MAX_BATCH = 200
"""Beyond this, the oldest waiting events of a type are dropped (and counted)."""


class RateLimiter:
    """Send events, batching those beyond ``limit`` per second and per type."""

    def __init__(
        self,
        send: Send,
        limit: int = 20,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._send = send
        self._limit = limit
        self._clock = clock
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[float, int]] = {}
        """Start of the current one-second window and events sent in it, by type."""

        self._waiting: dict[str, list[tuple[Any, Any]]] = {}
        """``(key, payload)`` of the events waiting for the next window, by type."""

        self._dropped: dict[str, int] = {}

    def emit(self, name: str, payload: Any, key: Any = None) -> None:
        """Send an event now, or keep it for the next batch.

        Args:
            name: The event type.
            payload: The event payload.
            key: Waiting events of a type with the same key replace each other
                (like the states of a node); ``None`` keeps them all.
        """
        now = self._clock()
        batch: list[Any] = []
        with self._lock:
            start, count = self._windows.get(name, (now, 0))
            if now - start >= 1.0:
                batch = self._take(name)
                start, count = now, 0
            send_now = count < self._limit
            self._windows[name] = (start, count + 1 if send_now else count)
            if not send_now:
                self._keep(name, payload, key)
        if batch:
            self._send("batch", {"event": name, "items": batch})
        if send_now:
            self._send(name, payload)

    def _keep(self, name: str, payload: Any, key: Any) -> None:
        waiting = self._waiting.setdefault(name, [])
        if key is not None:
            waiting[:] = [item for item in waiting if item[0] != key]
        waiting.append((key, payload))
        if len(waiting) > MAX_BATCH:
            del waiting[0]
            self._dropped[name] = self._dropped.get(name, 0) + 1

    def _take(self, name: str) -> list[Any]:
        """The payloads of the waiting events of a type, removed from the queue."""
        items = [payload for _, payload in self._waiting.pop(name, [])]
        dropped = self._dropped.pop(name, 0)
        if dropped:
            items.insert(0, {"dropped": dropped})
        return items

    def flush(self) -> None:
        """Send every waiting event now (periodically, and at the end of a run)."""
        with self._lock:
            batches = {name: self._take(name) for name in list(self._waiting)}
        for name, items in batches.items():
            if items:
                self._send("batch", {"event": name, "items": items})
