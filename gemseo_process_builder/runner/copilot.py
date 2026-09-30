"""The Claude copilot of a piloted run (docs/CLAUDE_PILOT_SPEC.md § 10.2).

A script piloted by Claude imports ``gemseo_claude_pilot``; the runner then
forwards the pilot's events on its event channel and passes the user's copilot
commands to the pilot. The runner never imports the plugin itself: a run
without copilot does not pay for it.
"""

import sys
from pathlib import Path
from typing import Any

from gemseo_process_builder.runner.rate_limiter import RateLimiter
from gemseo_process_builder.runner.rate_limiter import Send

EVENTS_MODULE = "gemseo_claude_pilot.events"

FOLDER_VARIABLE = "GEMSEO_CLAUDE_PILOT_FOLDER"
"""Tells the pilot where to write its journal."""

LATEST_ONLY = ("copilot.status", "copilot.usage")
"""Events whose latest value is enough; the others are all sent at once."""


def copilot_folder(run_folder: Path) -> Path:
    """The folder of the copilot's journal in a run folder (spec § 9.1)."""
    return run_folder / "copilot"


class CopilotLink:
    """Links the pilot of the script, if it has one, to the runner.

    Args:
        send: Sends an event at once.
        limiter: Sends frequent events, keeping the latest of each type.
    """

    def __init__(self, send: Send, limiter: RateLimiter) -> None:
        self._send = send
        self._limiter = limiter
        self.summary: dict[str, Any] | None = None
        """What the pilot reported at the end of its run."""

    def connect(self) -> bool:
        """Listen to the pilot, when the script imported it."""
        events = sys.modules.get(EVENTS_MODULE)
        if events is None:
            return False
        events.subscribe(self.forward)
        return True

    def close(self) -> None:
        """Stop listening to the pilot."""
        events = sys.modules.get(EVENTS_MODULE)
        if events is not None:
            events.unsubscribe(self.forward)

    def forward(self, kind: str, payload: dict[str, Any]) -> None:
        """Send an event of the pilot to the application."""
        if kind == "copilot.summary":
            self.summary = payload
        if kind in LATEST_ONLY:
            self._limiter.emit(kind, payload, key=kind)
        else:
            self._send(kind, payload)

    @staticmethod
    def command(message: dict[str, Any]) -> None:
        """Pass a command of the user to the pilot; ignored without a pilot."""
        events = sys.modules.get(EVENTS_MODULE)
        if events is not None:
            events.send_command(str(message.get("command")), message.get("params"))
