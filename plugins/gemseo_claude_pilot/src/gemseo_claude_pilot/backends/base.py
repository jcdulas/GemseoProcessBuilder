"""What every backend does: talk to Claude with the pilot's tools (spec § 5.1).

Two shapes:

- :class:`Backend` returns one turn at a time; the exchange runs the loop of
  tool calls (the API key backend, the fake backend of the tests);
- :class:`LoopingBackend` runs the loop itself and calls back for each tool
  call (Claude Code).

The rest of the package never knows which backend it talks to.
"""

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Literal
from typing import Protocol
from typing import runtime_checkable


@dataclass(frozen=True)
class ToolSpec:
    """A tool Claude may call."""

    name: str
    description: str
    input_schema: Mapping[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """A call of a tool by Claude."""

    id: str
    name: str
    input: Mapping[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """The answer to a tool call."""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Message:
    """A turn of the conversation."""

    role: Literal["user", "assistant"]
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    raw: Any = None
    """The turn as the backend received it, sent back unchanged when given."""


@dataclass(frozen=True)
class Usage:
    """The tokens a reply cost."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    """The estimated cost with an API key; 0 with a subscription."""

    @property
    def tokens(self) -> int:
        """The input and output tokens."""
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cached_tokens + other.cached_tokens,
            self.cost_usd + other.cost_usd,
        )


Effort = Literal["", "low", "medium", "high", "xhigh", "max"]
"""How much Claude thinks at a call; empty for the model's default."""

EFFORTS: tuple[Effort, ...] = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class Request:
    """A conversation to continue."""

    system: str
    messages: tuple[Message, ...]
    model: str
    tools: tuple[ToolSpec, ...] = ()
    max_tokens: int = 4096
    effort: Effort = ""
    """How much Claude thinks (``low`` … ``max``); the model's default if empty."""


@dataclass(frozen=True)
class Reply:
    """The next turn of Claude."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)
    stop_reason: str = "end_turn"
    raw: Any = None
    """The turn as the backend received it."""


class BackendError(Exception):
    """A call to Claude that failed."""

    retryable = False
    """Whether trying again later may work."""


class BackendTimeoutError(BackendError):
    """Claude did not answer in time."""

    retryable = True


class RateLimitError(BackendError):
    """Too many requests, or the usage limits of the plan are reached."""

    retryable = True


class AuthenticationError(BackendError):
    """The key or the login is missing or refused."""


class BackendUnavailableError(BackendError):
    """The backend cannot be used here: Claude Code or a package is missing."""


@dataclass(frozen=True)
class BackendStatus:
    """Whether a backend can be used, and what the user should know."""

    ok: bool
    message: str


ToolCallHandler = Callable[[ToolCall], ToolResult]
"""Answers a tool call of Claude."""


@runtime_checkable
class Backend(Protocol):
    """A way to talk to Claude."""

    name: str
    """A short name shown to the user, such as ``api_key``."""

    def send(self, request: Request) -> Reply:
        """Send a conversation and return the reply of Claude.

        Raises:
            BackendError: When the call fails.
        """
        ...


@runtime_checkable
class LoopingBackend(Protocol):
    """A way to talk to Claude that runs the loop of tool calls itself."""

    name: str

    def converse(self, request: Request, handle: ToolCallHandler) -> Reply:
        """Run the conversation, answering each tool call with ``handle``.

        Returns:
            The last text of Claude and the usage of the whole conversation.

        Raises:
            BackendError: When the conversation fails.
        """
        ...
