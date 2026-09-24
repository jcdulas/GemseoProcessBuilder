"""JSON-lines protocol between the application and its subprocesses.

The worker and the runner talk to the application with one JSON object per line:

- requests (application → subprocess, on stdin):
  ``{"id": "…", "method": "…", "params": {…}}``, or ``{"cancel": "<id>"}``;
- responses (subprocess → application, on stdout):
  ``{"id": "…", "ok": true, "result": …}`` or
  ``{"id": "…", "ok": false, "error": {"code", "message", "details"}}``;
- events (subprocess → application, on stdout): ``{"event": "…", "payload": …}``.

This module must stay importable without Qt and without GEMSEO.
"""

import json
import os
import sys
import threading
from typing import Any
from typing import TextIO

ENCODING = "utf-8"


def encode(message: dict[str, Any]) -> str:
    """Encode a message as one line of JSON, without the newline."""
    return json.dumps(message, ensure_ascii=False, default=_default)


def _default(value: Any) -> Any:
    """Convert values that JSON does not know (Pydantic models, numpy arrays)."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, set | tuple):
        return list(value)
    msg = f"Object of type {type(value).__name__} is not JSON serializable."
    raise TypeError(msg)


def decode(line: str) -> dict[str, Any] | None:
    """Decode one line; return ``None`` for blank or malformed lines."""
    line = line.strip()
    if not line:
        return None
    try:
        message = json.loads(line)
    except ValueError:
        return None
    return message if isinstance(message, dict) else None


def error_message(
    request_id: str, code: str, message: str, details: Any = None
) -> dict[str, Any]:
    """Build an error response."""
    return {
        "id": request_id,
        "ok": False,
        "error": {"code": code, "message": message, "details": details},
    }


def protected_stdin() -> TextIO:
    """Return a private reader of the protocol input and neutralize ``sys.stdin``.

    The request reader blocks on its input in a thread. If it used ``sys.stdin``,
    any library touching ``sys.stdin`` meanwhile (some do at import time) would
    wait for the reader's lock forever. The protocol therefore reads a duplicate
    of file descriptor 0, and ``sys.stdin`` becomes an empty stream.
    """
    protocol_fd = os.dup(0)
    null_fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null_fd, 0)
    os.close(null_fd)
    if sys.platform == "win32":
        _point_std_input_to_fd_0()
    sys.stdin = open(os.devnull, encoding=ENCODING)  # noqa: SIM115
    return os.fdopen(protocol_fd, "r", encoding=ENCODING, newline="\n")


def _point_std_input_to_fd_0() -> None:
    """Make the Windows standard input handle refer to fd 0 (now ``NUL``).

    Every DLL loaded later queries the standard handles during its
    initialization. While a thread waits in a synchronous read on the protocol
    pipe, such a query on the same pipe blocks, and the import hangs forever.
    """
    import ctypes
    import msvcrt

    std_input_handle = -10
    ctypes.windll.kernel32.SetStdHandle(std_input_handle, msvcrt.get_osfhandle(0))


class EventChannel:
    """The protected output of a subprocess.

    At creation, the original standard output is duplicated for the protocol,
    then standard output is redirected to standard error. Anything printed by
    user code or by libraries therefore goes to stderr and cannot corrupt the
    protocol.

    Args:
        stream: A stream to write to instead of the protected stdout (tests).
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self._lock = threading.Lock()
        if stream is not None:
            self._stream = stream
            return
        sys.stdout.flush()
        protocol_fd = os.dup(1)
        os.dup2(2, 1)
        sys.stdout = sys.stderr
        self._stream = os.fdopen(
            protocol_fd, "w", encoding=ENCODING, buffering=1, newline="\n"
        )

    def send(self, message: dict[str, Any]) -> None:
        """Write one message (thread-safe)."""
        line = encode(message) + "\n"
        with self._lock:
            self._stream.write(line)
            self._stream.flush()

    def event(self, name: str, payload: Any = None) -> None:
        """Send an event."""
        self.send({"event": name, "payload": payload})
