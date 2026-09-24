"""Forward Python log records to the page's Console panel."""

import logging
import time
from collections import deque
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtCore import Signal
from PySide6.QtCore import Slot

from gemseo_process_builder.app.bridge import Bridge

HISTORY_SIZE = 500
"""Records kept for the page, which may connect after they were emitted."""

MAX_RECORDS_PER_SECOND = 200


class RateLimiter:
    """Allow at most ``limit`` events per one-second window, counting the rest."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._window_start = 0.0
        self._count = 0
        self.dropped = 0

    def allow(self, now: float) -> bool:
        """Tell whether an event happening at ``now`` (seconds) is allowed."""
        if now - self._window_start >= 1.0:
            self._window_start = now
            self._count = 0
        self._count += 1
        if self._count > self.limit:
            self.dropped += 1
            return False
        return True

    def take_dropped(self) -> int:
        """Return and reset the number of dropped events."""
        dropped, self.dropped = self.dropped, 0
        return dropped


def record_to_dict(record: logging.LogRecord, source: str = "app") -> dict[str, Any]:
    """Convert a log record into a Console line."""
    message = record.getMessage()
    if record.exc_info and record.exc_info[1] is not None:
        message += f"\n{logging.Formatter().formatException(record.exc_info)}"
    return {
        "time": record.created,
        "level": record.levelname,
        "source": source,
        "logger": record.name,
        "message": message,
    }


class _MainThreadPusher(QObject):
    """Push log lines to the page from the Qt thread."""

    line_ready = Signal(object)

    def __init__(self, bridge: Bridge, history: deque[dict[str, Any]]) -> None:
        super().__init__()
        self._bridge = bridge
        self._history = history
        # Emitted from any thread, delivered in the Qt thread (queued connection).
        self.line_ready.connect(self._push)

    @Slot(object)
    def _push(self, line: dict[str, Any]) -> None:
        self._history.append(line)
        self._bridge.emit_event("app.log", line)


class LogForwarder(logging.Handler):
    """A logging handler sending records to the page as ``app.log`` events.

    Records may come from any thread; they are marshalled to the Qt thread
    through a signal before being pushed to the page.
    """

    def __init__(self, bridge: Bridge, level: int = logging.DEBUG) -> None:
        super().__init__(level)
        self.history: deque[dict[str, Any]] = deque(maxlen=HISTORY_SIZE)
        self._limiter = RateLimiter(MAX_RECORDS_PER_SECOND)
        self._pusher = _MainThreadPusher(bridge, self.history)

    def emit(self, record: logging.LogRecord) -> None:
        """Queue a record for the page (logging callback)."""
        if record.name.startswith("gemseo_process_builder.app.bridge"):
            return  # Avoid feedback loops: pushing a record logs bridge activity.
        if not self._limiter.allow(time.monotonic()):
            return
        line = record_to_dict(record)
        dropped = self._limiter.take_dropped()
        if dropped:
            line["message"] = f"({dropped} messages skipped) {line['message']}"
        self._pusher.line_ready.emit(line)


def register_log_methods(bridge: Bridge, forwarder: LogForwarder) -> None:
    """Register ``app.logs``, returning the records emitted so far."""
    bridge.registry.add("app.logs", lambda: list(forwarder.history))
