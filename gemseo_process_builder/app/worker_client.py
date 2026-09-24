"""The application side of the introspection worker (SPEC § 3.1, § 14.2).

The client starts the worker with ``QProcess``, sends requests, matches the
responses, restarts the worker when it crashes, and reports its status:
``stopped``, ``starting``, ``ready``, ``busy``, ``crashed`` or ``incompatible``.

Requests can be sent from any thread; ``call`` blocks the calling thread and must
not be used from the Qt thread (use ``request`` with a callback there).
"""

import logging
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtCore import QProcess
from PySide6.QtCore import QProcessEnvironment
from PySide6.QtCore import QThread
from PySide6.QtCore import QTimer
from PySide6.QtCore import Signal
from PySide6.QtCore import Slot

from gemseo_process_builder.workers.protocol import decode
from gemseo_process_builder.workers.protocol import encode

_LOGGER = logging.getLogger(__name__)
_WORKER_LOGGER = logging.getLogger("worker")

PACKAGE_PARENT = str(Path(__file__).resolve().parent.parent.parent)
"""Added to the worker's PYTHONPATH, so another interpreter finds this package."""

DEFAULT_TIMEOUT_S = 60.0
MAX_RESTARTS = 3
RESTART_WINDOW_S = 60.0


class WorkerUnavailableError(Exception):
    """The worker could not answer (not running, crashed or too slow)."""


class WorkerRequestError(Exception):
    """The worker answered with an error."""

    def __init__(self, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


@dataclass
class _Pending:
    method: str
    deadline: float
    callback: Callable[[dict[str, Any]], None]


@dataclass
class WorkerStatus:
    """The state of the worker, shown in the status bar."""

    state: str = "stopped"
    detail: str = ""
    versions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """The status sent to the page."""
        return {"state": self.state, "detail": self.detail, "versions": self.versions}


def check_versions(versions: dict[str, str]) -> str:
    """Return why the worker's environment is incompatible, or an empty string."""
    python = tuple(int(part) for part in versions.get("python", "0.0").split(".")[:2])
    if python < (3, 12):
        return f"Python {versions.get('python')} is too old: 3.12 or newer is needed."
    if not versions.get("pydantic", "").startswith("2."):
        return f"Pydantic {versions.get('pydantic')} is not supported: 2.x is needed."
    gemseo = versions.get("gemseo")
    if gemseo is not None and not gemseo.startswith("6."):
        return f"GEMSEO {gemseo} is not supported: 6.x is needed."
    return ""


class WorkerClient(QObject):
    """Start, talk to and supervise a worker subprocess.

    Args:
        interpreter: The Python interpreter; empty means the application's one.
        module: The worker module run with ``-m``.
        arguments: Extra arguments (used by tests to run a script instead).
    """

    status_changed = Signal(dict)
    event_received = Signal(str, object)
    _send = Signal(str)

    def __init__(
        self,
        interpreter: str = "",
        module: str = "gemseo_process_builder.workers.introspection",
        arguments: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.interpreter = interpreter
        self.module = module
        self.arguments = arguments
        self.status = WorkerStatus()
        self._process: QProcess | None = None
        self._buffer = b""
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.Lock()
        self._restarts: list[float] = []
        self._stopping = False
        self._send.connect(self._write)
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._check_deadlines)
        self._timer.start()

    # Lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        """Start the worker (does nothing if it is running)."""
        if self._process is not None:
            return
        self._stopping = False
        process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        paths = [PACKAGE_PARENT]
        if environment.contains("PYTHONPATH"):
            paths.append(environment.value("PYTHONPATH"))
        environment.insert(
            "PYTHONPATH",
            ";".join(paths) if sys.platform == "win32" else ":".join(paths),
        )
        environment.insert("PYTHONUNBUFFERED", "1")
        environment.insert("PYTHONIOENCODING", "utf-8")
        process.setProcessEnvironment(environment)
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._error_occurred)
        self._process = process
        self._buffer = b""
        self._set_status("starting", "")
        program = self.interpreter or sys.executable
        arguments = (
            self.arguments if self.arguments is not None else ["-m", self.module]
        )
        process.start(program, arguments)

    def stop(self) -> None:
        """Stop the worker and fail the pending requests."""
        self._stopping = True
        process, self._process = self._process, None
        if process is not None:
            process.closeWriteChannel()
            if not process.waitForFinished(1000):
                process.kill()
                process.waitForFinished(1000)
            process.deleteLater()
        self._fail_all("The worker was stopped.")
        self._set_status("stopped", "")

    def restart(self) -> None:
        """Stop then start the worker; resets the crash counter."""
        self._restarts.clear()
        self.stop()
        self.start()

    # Requests ------------------------------------------------------------------

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        callback: Callable[[dict[str, Any]], None] | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> str:
        """Send a request; ``callback`` receives the response (any thread).

        Returns:
            The request id, which can be passed to ``cancel``.
        """
        request_id = uuid.uuid4().hex
        with self._lock:
            self._pending[request_id] = _Pending(
                method, time.monotonic() + timeout, callback or (lambda _: None)
            )
        self._send.emit(
            encode({"id": request_id, "method": method, "params": params or {}})
        )
        return request_id

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> Any:
        """Send a request and wait for its result (not from the Qt thread).

        Raises:
            WorkerUnavailableError: When the worker does not answer.
            WorkerRequestError: When the worker answers with an error.
        """
        if QThread.currentThread() is self.thread():
            msg = "WorkerClient.call would block the Qt thread; use request()."
            raise RuntimeError(msg)
        done = threading.Event()
        box: dict[str, Any] = {}

        def store(response: dict[str, Any]) -> None:
            box.update(response)
            done.set()

        self.request(method, params, store, timeout)
        done.wait(timeout + 5)
        return unwrap(box)

    def cancel(self, request_id: str) -> None:
        """Ask the worker to cancel a request."""
        self._send.emit(encode({"cancel": request_id}))

    # Internals -----------------------------------------------------------------

    @Slot(str)
    def _write(self, line: str) -> None:
        if self._process is None:
            self.start()
        process = self._process
        if process is None:
            return
        process.write((line + "\n").encode("utf-8"))
        self._update_busy()

    def _read_stdout(self) -> None:
        if self._process is None:
            return
        self._buffer += bytes(self._process.readAllStandardOutput().data())
        *lines, self._buffer = self._buffer.split(b"\n")
        for line in lines:
            message = decode(line.decode("utf-8", errors="replace"))
            if message is not None:
                self._handle(message)

    def _read_stderr(self) -> None:
        if self._process is None:
            return
        text = bytes(self._process.readAllStandardError().data()).decode(
            "utf-8", errors="replace"
        )
        for line in text.splitlines():
            if line.strip():
                _WORKER_LOGGER.warning(line)

    def _handle(self, message: dict[str, Any]) -> None:
        if "event" in message:
            self._handle_event(str(message["event"]), message.get("payload"))
            return
        request_id = str(message.get("id", ""))
        with self._lock:
            pending = self._pending.pop(request_id, None)
        if pending is not None:
            pending.callback(message)
        self._update_busy()

    def _handle_event(self, name: str, payload: Any) -> None:
        if name == "ready":
            self.status.versions = dict(payload or {})
            problem = check_versions(self.status.versions)
            self._set_status(
                "incompatible" if problem else "ready", problem or "Loading GEMSEO…"
            )
        elif name == "gemseo_loaded":
            self.status.versions.update(payload or {})
            problem = check_versions(self.status.versions)
            detail = problem or f"GEMSEO {self.status.versions.get('gemseo')}"
            self._set_status("incompatible" if problem else self.status.state, detail)
        elif name == "gemseo_failed":
            self._set_status(
                "incompatible", f"GEMSEO cannot be imported: {payload['error']}"
            )
        elif name == "log":
            level = logging.getLevelName(payload.get("level", "INFO"))
            _WORKER_LOGGER.log(
                level if isinstance(level, int) else logging.INFO,
                "%s",
                payload.get("message", ""),
            )
        self.event_received.emit(name, payload)

    def _update_busy(self) -> None:
        if self.status.state not in ("ready", "busy"):
            return
        with self._lock:
            busy = bool(self._pending)
        state = "busy" if busy else "ready"
        if state != self.status.state:
            self._set_status(state, self.status.detail)

    def _check_deadlines(self) -> None:
        now = time.monotonic()
        with self._lock:
            late = [
                rid for rid, pending in self._pending.items() if pending.deadline < now
            ]
        if not late:
            return
        with self._lock:
            methods = [
                self._pending[rid].method for rid in late if rid in self._pending
            ]
        _LOGGER.warning(
            "The worker did not answer %s in time: restarting it.", ", ".join(methods)
        )
        self._fail(late, "The worker did not answer in time.")
        self._crash_restart("timeout")

    def _fail(self, request_ids: list[str], message: str) -> None:
        for request_id in request_ids:
            with self._lock:
                pending = self._pending.pop(request_id, None)
            if pending is not None:
                pending.callback(
                    {
                        "id": request_id,
                        "ok": False,
                        "error": {
                            "code": "worker_unavailable",
                            "message": message,
                            "details": None,
                        },
                    }
                )

    def _fail_all(self, message: str) -> None:
        with self._lock:
            ids = list(self._pending)
        self._fail(ids, message)

    def _finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if self._stopping:
            return
        _LOGGER.warning("The worker stopped unexpectedly (exit code %s).", exit_code)
        self._crash_restart(f"exit code {exit_code}")

    def _error_occurred(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._process = None
            self._fail_all("The worker could not be started.")
            self._set_status(
                "crashed",
                f"Cannot start {self.interpreter or sys.executable}: check the "
                "Python interpreter in the preferences.",
            )

    def _crash_restart(self, reason: str) -> None:
        process, self._process = self._process, None
        if process is not None:
            self._stopping = True
            process.kill()
            process.waitForFinished(1000)
            process.deleteLater()
            self._stopping = False
        self._fail_all(f"The worker stopped ({reason}).")
        now = time.monotonic()
        self._restarts = [t for t in self._restarts if now - t < RESTART_WINDOW_S]
        if len(self._restarts) >= MAX_RESTARTS:
            self._set_status(
                "crashed",
                f"The worker keeps stopping ({reason}). Use Tools > Restart worker.",
            )
            return
        self._restarts.append(now)
        self._set_status("starting", f"Restarting after a problem ({reason})")
        self.start()

    def _set_status(self, state: str, detail: str) -> None:
        self.status.state = state
        self.status.detail = detail
        self.status_changed.emit(self.status.to_dict())


def unwrap(response: dict[str, Any]) -> Any:
    """Return the result of a response, or raise its error."""
    if not response:
        msg = "The worker did not answer."
        raise WorkerUnavailableError(msg)
    if response.get("ok"):
        return response.get("result")
    error = response.get("error") or {}
    if error.get("code") == "worker_unavailable":
        raise WorkerUnavailableError(error.get("message", "The worker is unavailable."))
    raise WorkerRequestError(
        error.get("code", "internal"), error.get("message", ""), error.get("details")
    )
