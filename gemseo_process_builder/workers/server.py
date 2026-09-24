"""The request loop of a worker subprocess.

Requests are read from stdin by a reader thread and processed one at a time by
the main thread. A request can be cancelled: the handler checks
``context.cancelled`` at safe points, or calls ``context.check()``.
"""

import contextlib
import logging
import queue
import sys
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import TextIO

from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.protocol import decode
from gemseo_process_builder.workers.protocol import error_message


class WorkerError(Exception):
    """An error reported to the application with a code."""

    def __init__(self, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class CancelledError(WorkerError):
    """The application cancelled the request."""

    def __init__(self) -> None:
        super().__init__("cancelled", "The request was cancelled.")


@dataclass
class RequestContext:
    """What a handler knows about the request it serves."""

    request_id: str
    channel: EventChannel
    _cancelled: threading.Event = field(default_factory=threading.Event)

    @property
    def cancelled(self) -> bool:
        """Whether the application cancelled the request."""
        return self._cancelled.is_set()

    def check(self) -> None:
        """Raise ``CancelledError`` if the request was cancelled."""
        if self.cancelled:
            raise CancelledError

    def cancel(self) -> None:
        """Mark the request as cancelled."""
        self._cancelled.set()


Handler = Callable[[dict[str, Any], RequestContext], Any]


class ChannelLogHandler(logging.Handler):
    """Send log records to the application as ``log`` events."""

    def __init__(self, channel: EventChannel) -> None:
        super().__init__(logging.DEBUG)
        self._channel = channel

    def emit(self, record: logging.LogRecord) -> None:
        """Send one record (logging callback)."""
        message = record.getMessage()
        if record.exc_info and record.exc_info[1] is not None:
            message += "\n" + logging.Formatter().formatException(record.exc_info)
        with contextlib.suppress(OSError, ValueError):  # The application is gone.
            self._channel.event(
                "log",
                {
                    "time": record.created,
                    "level": record.levelname,
                    "logger": record.name,
                    "message": message,
                },
            )


class WorkerServer:
    """Dispatch requests to registered methods.

    Args:
        channel: Where responses and events go.
    """

    def __init__(self, channel: EventChannel) -> None:
        self.channel = channel
        self._methods: dict[str, Handler] = {}
        self._contexts: dict[str, RequestContext] = {}
        self._lock = threading.Lock()

    def method(self, name: str) -> Callable[[Handler], Handler]:
        """Register the decorated function as a method."""

        def register(handler: Handler) -> Handler:
            self._methods[name] = handler
            return handler

        return register

    def add(self, name: str, handler: Handler) -> None:
        """Register a method."""
        self._methods[name] = handler

    def cancel(self, request_id: str) -> None:
        """Cancel a request that is queued or running."""
        with self._lock:
            context = self._contexts.get(request_id)
        if context is not None:
            context.cancel()

    def context_for(self, request_id: str) -> RequestContext:
        """Create the context of a request (so it can be cancelled early)."""
        with self._lock:
            return self._contexts.setdefault(
                request_id, RequestContext(request_id, self.channel)
            )

    def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        """Process one request and return its response."""
        request_id = str(message.get("id", ""))
        method = message.get("method")
        params = message.get("params") or {}
        if not isinstance(method, str) or not isinstance(params, dict):
            return error_message(request_id, "invalid_request", "Malformed request.")
        handler = self._methods.get(method)
        if handler is None:
            return error_message(
                request_id, "unknown_method", f"Unknown method {method!r}."
            )
        context = self.context_for(request_id)
        try:
            context.check()
            result = handler(params, context)
        except WorkerError as error:
            return error_message(request_id, error.code, error.message, error.details)
        except Exception as error:
            logging.getLogger(__name__).debug("Method %s failed", method, exc_info=True)
            return error_message(
                request_id,
                "internal",
                str(error) or type(error).__name__,
                traceback.format_exception(error),
            )
        finally:
            with self._lock:
                self._contexts.pop(request_id, None)
        return {"id": request_id, "ok": True, "result": result}

    def serve(self, stdin: TextIO | None = None) -> None:
        """Serve requests until stdin is closed."""
        requests: queue.Queue[dict[str, Any] | None] = queue.Queue()
        reader = threading.Thread(
            target=self._read, args=(stdin or sys.stdin, requests), daemon=True
        )
        reader.start()
        while True:
            message = requests.get()
            if message is None:
                return
            self.channel.send(self.handle(message))

    def _read(
        self, stdin: TextIO, requests: "queue.Queue[dict[str, Any] | None]"
    ) -> None:
        for line in stdin:
            message = decode(line)
            if message is None:
                continue
            if "cancel" in message:
                self.cancel(str(message["cancel"]))
            else:
                self.context_for(str(message.get("id", "")))
                requests.put(message)
        requests.put(None)


def setup_worker_logging(channel: EventChannel, level: int = logging.INFO) -> None:
    """Send the logs of the subprocess to the application."""
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(ChannelLogHandler(channel))
    root.setLevel(level)
