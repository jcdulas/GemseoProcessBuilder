"""Stopping a run on request (SPEC § 11.4).

The application writes ``{"command": "stop"}`` on the runner's standard input.
A thread reads it and raises a flag; the instrumentation checks the flag at
each iteration, sample or discipline execution and raises ``RunStopped``, which
GEMSEO lets through: the run ends cleanly and its history is saved.
"""

import threading
from collections.abc import Callable
from typing import Any
from typing import TextIO

from gemseo_process_builder.workers.protocol import decode


class RunStopped(Exception):  # noqa: N818 - reads better than RunStoppedError
    """The user asked the run to stop."""


class StopFlag:
    """Set when the application asks the run to stop."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def set(self) -> None:
        """Ask the run to stop."""
        self._event.set()

    @property
    def is_set(self) -> bool:
        """Whether the run must stop."""
        return self._event.is_set()

    def check(self) -> None:
        """Raise ``RunStopped`` if the run must stop."""
        if self._event.is_set():
            raise RunStopped

    def listen(
        self,
        commands: TextIO,
        other: Callable[[dict[str, Any]], None] | None = None,
    ) -> threading.Thread:
        """Read the commands in a thread; ``stop`` (or a closed input) sets the flag.

        Args:
            commands: The input the application writes its commands to.
            other: Receives every command, ``stop`` included (the copilot
                commands, for the Claude copilot).
        """

        def read() -> None:
            for line in commands:
                message = decode(line)
                if message is None:
                    continue
                if other is not None:
                    other(message)
                if message.get("command") == "stop":
                    self.set()
                    return
            self.set()  # The application went away.

        thread = threading.Thread(target=read, name="stop-listener", daemon=True)
        thread.start()
        return thread
