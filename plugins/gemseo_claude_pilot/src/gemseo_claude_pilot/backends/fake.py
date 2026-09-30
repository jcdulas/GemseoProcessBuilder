"""A backend that replays scripted answers, for tests and demos (spec § 12).

Example:
    >>> backend = FakeBackend([FakeBackend.decision({"diagnosis": "All is well."})])
    >>> reply = backend.send(Request(system="", messages=(), model="any"))
    >>> reply.tool_calls[0].name
    'submit_decision'
"""

import time
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from gemseo_claude_pilot.backends.base import BackendError
from gemseo_claude_pilot.backends.base import Reply
from gemseo_claude_pilot.backends.base import Request
from gemseo_claude_pilot.backends.base import ToolCall
from gemseo_claude_pilot.backends.base import Usage


@dataclass(frozen=True)
class Delayed:
    """An answer given after a delay, in seconds."""

    delay: float
    answer: "Reply | BackendError"


Answer = Reply | BackendError | Delayed


class FakeBackend:
    """Replays a script of answers and records the requests it received.

    Args:
        script: The answers, in order: replies, errors to raise, or delayed
            ones.
        then: The answer once the script is over; an error by default.
    """

    name = "fake"

    def __init__(self, script: Iterable[Answer], then: Answer | None = None) -> None:
        self._script = list(script)
        self._then = then
        self.requests: list[Request] = []

    def send(self, request: Request) -> Reply:
        """The next answer of the script.

        Raises:
            BackendError: When the script says so, or when it is over.
        """
        self.requests.append(request)
        if self._script:
            answer = self._script.pop(0)
        elif self._then is not None:
            answer = self._then
        else:
            raise BackendError("The fake backend has no more answers.")
        if isinstance(answer, Delayed):
            time.sleep(answer.delay)
            answer = answer.answer
        if isinstance(answer, BackendError):
            raise answer
        return answer

    @staticmethod
    def decision(decision: Mapping[str, Any], text: str = "") -> Reply:
        """A reply submitting a decision."""
        return FakeBackend.tool(("submit_decision", decision), text=text)

    @staticmethod
    def tool(*calls: tuple[str, Mapping[str, Any]], text: str = "") -> Reply:
        """A reply calling tools."""
        return Reply(
            text=text,
            tool_calls=tuple(
                ToolCall(f"call_{index}", name, dict(arguments))
                for index, (name, arguments) in enumerate(calls)
            ),
            usage=Usage(input_tokens=1000, output_tokens=100),
            stop_reason="tool_use",
        )

    @staticmethod
    def text(text: str) -> Reply:
        """A reply in words."""
        return Reply(text=text, usage=Usage(input_tokens=1000, output_tokens=100))
