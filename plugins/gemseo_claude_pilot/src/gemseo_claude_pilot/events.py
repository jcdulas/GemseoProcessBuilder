"""The channel between the pilot and the process that runs it (spec § 10.2).

The runner of GEMSEO Process Builder subscribes to the pilot's events and
forwards them to the application; it passes the user's commands back. In a
plain script, nobody listens: events go nowhere and no command comes.

Events: ``copilot.status``, ``copilot.message``, ``copilot.usage``,
``copilot.segment``, ``copilot.summary``. Commands: ``copilot.accept``,
``copilot.reject``, ``copilot.mode``.
"""

import logging
import queue
from collections.abc import Callable
from typing import Any

LOGGER = logging.getLogger(__name__)

Listener = Callable[[str, dict[str, Any]], None]
"""Receives the kind and the payload of an event."""

_listeners: list[Listener] = []
_commands: "queue.SimpleQueue[tuple[str, dict[str, Any]]]" = queue.SimpleQueue()


def subscribe(listener: Listener) -> None:
    """Receive the pilot's events."""
    _listeners.append(listener)


def unsubscribe(listener: Listener) -> None:
    """Stop receiving the pilot's events."""
    if listener in _listeners:
        _listeners.remove(listener)


def connected() -> bool:
    """Whether a process listens to the pilot, so that the user can answer it."""
    return bool(_listeners)


def publish(kind: str, payload: dict[str, Any]) -> None:
    """Send an event to the listeners; a failing listener never stops the run."""
    for listener in list(_listeners):
        try:
            listener(kind, payload)
        except Exception as error:  # The run never depends on its listeners.
            LOGGER.warning("A listener of the Claude pilot failed: %s", error)


def send_command(name: str, params: dict[str, Any] | None = None) -> None:
    """Pass a command of the user to the pilot (from any thread)."""
    _commands.put((name, dict(params or {})))


def take_commands() -> list[tuple[str, dict[str, Any]]]:
    """The commands received since the last call."""
    commands = []
    while True:
        try:
            commands.append(_commands.get_nowait())
        except queue.Empty:
            return commands
