"""Opening a GEMSEO script as a project (SPEC § 3.5).

The worker runs the script until its study would start and returns the
project it built (``script.read``); the project then replaces the current
one, in the Qt thread. Reading can take a few seconds: the page is told when
it starts, ends or fails.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtCore import Signal

from gemseo_process_builder.app.worker_client import WorkerClient

READ_TIMEOUT_S = 600.0


class ScriptReading(QObject):
    """Read scripts in the worker; hand the results over in the Qt thread."""

    _read = Signal(object, object)

    def __init__(
        self, worker: WorkerClient, done: Callable[[Path, dict[str, Any]], None]
    ) -> None:
        super().__init__()
        self.worker = worker
        # A queued connection: the worker answers in its own thread.
        self._read.connect(done)

    def start(self, path: Path) -> None:
        """Read a script; ``done(path, response)`` follows in the Qt thread."""
        self.worker.request(
            "script.read",
            {"path": str(path)},
            lambda response: self._read.emit(path, response),
            timeout=READ_TIMEOUT_S,
        )
