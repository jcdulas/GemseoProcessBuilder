"""The ways to talk to Claude (spec § 5).

The backend is chosen by name: ``claude_code`` (the default, the user's own
Claude Code and subscription), ``api_key`` (the Messages API, billed per token)
or ``off``. GEMSEO Process Builder passes the user's choice to the runner in
``GEMSEO_CLAUDE_PILOT_BACKEND``.
"""

import os

from gemseo_claude_pilot.backends.base import AuthenticationError
from gemseo_claude_pilot.backends.base import Backend
from gemseo_claude_pilot.backends.base import BackendError
from gemseo_claude_pilot.backends.base import BackendStatus
from gemseo_claude_pilot.backends.base import BackendTimeoutError
from gemseo_claude_pilot.backends.base import BackendUnavailableError
from gemseo_claude_pilot.backends.base import LoopingBackend
from gemseo_claude_pilot.backends.base import Message
from gemseo_claude_pilot.backends.base import RateLimitError
from gemseo_claude_pilot.backends.base import Reply
from gemseo_claude_pilot.backends.base import Request
from gemseo_claude_pilot.backends.base import ToolCall
from gemseo_claude_pilot.backends.base import ToolResult
from gemseo_claude_pilot.backends.base import ToolSpec
from gemseo_claude_pilot.backends.base import Usage
from gemseo_claude_pilot.backends.fake import FakeBackend

__all__ = [
    "AuthenticationError",
    "Backend",
    "BackendError",
    "BackendStatus",
    "BackendTimeoutError",
    "BackendUnavailableError",
    "FakeBackend",
    "LoopingBackend",
    "Message",
    "RateLimitError",
    "Reply",
    "Request",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "Usage",
    "create_backend",
]

BACKEND_VARIABLE = "GEMSEO_CLAUDE_PILOT_BACKEND"
"""The environment variable naming the backend."""

BACKEND_NAMES = ("claude_code", "api_key", "off")


def create_backend(name: str | None = None) -> Backend | LoopingBackend | None:
    """The backend of a name, by default the one of the environment.

    Returns:
        The backend, or ``None`` for ``off``.

    Raises:
        ValueError: When the name is unknown.
    """
    name = name or os.environ.get(BACKEND_VARIABLE) or "claude_code"
    if name == "claude_code":
        from gemseo_claude_pilot.backends.claude_code import ClaudeCodeBackend

        return ClaudeCodeBackend()
    if name == "api_key":
        from gemseo_claude_pilot.backends.api import ApiKeyBackend

        return ApiKeyBackend()
    if name == "off":
        return None
    raise ValueError(
        f"Unknown backend {name!r}: choose one of {', '.join(BACKEND_NAMES)}."
    )
