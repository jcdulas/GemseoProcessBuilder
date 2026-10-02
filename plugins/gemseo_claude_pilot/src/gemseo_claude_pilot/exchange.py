"""One exchange with Claude: from a context to a checked decision (spec § 4.3, § 6).

Claude may call read tools, then submits a decision. A decision that is not
valid, or that breaks a limit, is sent back once with the reason so that
Claude can correct it; a second failure ends the exchange without decision.

:class:`ToolCalls` answers the tool calls; :func:`exchange` runs the loop for
backends that return one turn at a time, and lets the others (Claude Code) run
it themselves with the same answers.
"""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from gemseo_claude_pilot.backends.base import Backend
from gemseo_claude_pilot.backends.base import Effort
from gemseo_claude_pilot.backends.base import LoopingBackend
from gemseo_claude_pilot.backends.base import Message
from gemseo_claude_pilot.backends.base import Request
from gemseo_claude_pilot.backends.base import ToolCall
from gemseo_claude_pilot.backends.base import ToolResult
from gemseo_claude_pilot.backends.base import ToolSpec
from gemseo_claude_pilot.backends.base import Usage
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.guardrails import Checked
from gemseo_claude_pilot.guardrails import RejectedDecisionError
from gemseo_claude_pilot.tools import SUBMIT_DECISION
from gemseo_claude_pilot.tools import TOOLS

MAX_TOOL_CALLS = 8
"""Read tool calls allowed in one exchange."""

MAX_CORRECTIONS = 1
"""Rejected decisions sent back to Claude before giving up."""

ToolHandler = Callable[[ToolCall], str]
"""Answers a read tool call; raises to report an error to Claude."""


@dataclass(frozen=True)
class Exchange:
    """What an exchange gave."""

    checked: Checked | None
    """The decision that passed the checks, if any."""

    text: str
    """What Claude wrote besides its tool calls, such as an answer to a question."""

    usage: Usage
    messages: tuple[Message, ...]
    rejections: tuple[str, ...] = ()
    """Why the decisions that failed were refused."""


class ToolCalls:
    """Answers the tool calls of one exchange, and keeps what they gave.

    Args:
        check: Translates and checks a decision; raises
            :class:`RejectedDecisionError` to refuse it.
        answer_tool: Answers the read tools; without it, they report that
            they are not available.
        max_tool_calls: The read tool calls allowed.
        review: Gives the request for review of a decision that passed the
            checks, or nothing; the first decision it asks to review is sent
            back to Claude, which submits it again, as it was or revised.
    """

    def __init__(
        self,
        check: Callable[[Decision], Checked],
        answer_tool: ToolHandler | None = None,
        max_tool_calls: int = MAX_TOOL_CALLS,
        review: Callable[[Decision], str] | None = None,
    ) -> None:
        self._check = check
        self._review = review
        self.reviewed = False
        """Whether a decision was sent back for review: it is, at most once."""

        self._answer_tool = answer_tool
        self._max_tool_calls = max_tool_calls
        self.checked: Checked | None = None
        self.rejections: list[str] = []
        self.read_calls = 0

    @property
    def finished(self) -> bool:
        """Whether the exchange is over: a decision passed, or too many failed."""
        return (
            self.checked is not None
            or len(self.rejections) > MAX_CORRECTIONS
            or self.read_calls > self._max_tool_calls + 2
        )

    def __call__(self, call: ToolCall) -> ToolResult:
        """The answer to a tool call."""
        if self.finished:
            return ToolResult(call.id, "The exchange is over: end your turn.", True)
        if call.name == SUBMIT_DECISION.name:
            return self._decide(call)
        self.read_calls += 1
        if self.read_calls > self._max_tool_calls:
            return ToolResult(
                call.id, "Too many tool calls: submit your decision now.", True
            )
        if self._answer_tool is None:
            return ToolResult(call.id, f"The tool {call.name} is not available.", True)
        try:
            return ToolResult(call.id, self._answer_tool(call))
        except Exception as error:  # Any error of a tool is reported to Claude.
            return ToolResult(call.id, f"The tool {call.name} failed: {error}", True)

    def _decide(self, call: ToolCall) -> ToolResult:
        try:
            checked = self._check(Decision.model_validate(call.input))
            request = (
                self._review(checked.decision)
                if self._review is not None and not self.reviewed
                else ""
            )
            if request:
                self.reviewed = True
                return ToolResult(call.id, request)  # Not recorded: Claude reviews it.
            self.checked = checked
        except (ValidationError, RejectedDecisionError) as error:
            reason = _reason(error)
            self.rejections.append(reason)
            if self.finished:
                reason += "\nNo more corrections: end your turn."
            return ToolResult(call.id, reason, True)
        notes = "".join(f"\n- {note}" for note in self.checked.notes)
        adjusted = f"\nAdjusted:{notes}" if notes else ""
        return ToolResult(call.id, f"Decision recorded.{adjusted} End your turn.")


def exchange(
    backend: Backend | LoopingBackend,
    system: str,
    model: str,
    context: str,
    check: Callable[[Decision], Checked],
    answer_tool: ToolHandler | None = None,
    tools: tuple[ToolSpec, ...] = TOOLS,
    max_tool_calls: int = MAX_TOOL_CALLS,
    effort: Effort = "",
    review: Callable[[Decision], str] | None = None,
) -> Exchange:
    """Ask Claude for a decision, and check it.

    Args:
        backend: The way to Claude.
        system: The system prompt.
        model: The model.
        context: The context of the call, as text.
        check: Translates and checks a decision; raises
            :class:`RejectedDecisionError` to refuse it.
        answer_tool: Answers the read tools; without it, they report that
            they are not available.
        tools: The tools Claude may call.
        max_tool_calls: The read tool calls allowed.
        effort: How much Claude thinks; the model's default if empty.
        review: Gives the request for review of a decision that passed the
            checks, or nothing.

    Raises:
        BackendError: When a call to Claude fails.
    """
    calls = ToolCalls(check, answer_tool, max_tool_calls, review)
    messages = [Message("user", text=context)]
    if isinstance(backend, LoopingBackend):
        reply = backend.converse(
            Request(system, tuple(messages), model, tools, effort=effort), calls
        )
        return Exchange(
            calls.checked, reply.text, reply.usage, (), tuple(calls.rejections)
        )
    usage = Usage()
    texts: list[str] = []
    while True:
        reply = backend.send(
            Request(system, tuple(messages), model, tools, effort=effort)
        )
        usage += reply.usage
        messages.append(
            Message("assistant", reply.text, reply.tool_calls, raw=reply.raw)
        )
        if reply.text:
            texts.append(reply.text)
        if not reply.tool_calls:
            break
        results = tuple(calls(call) for call in reply.tool_calls)
        if calls.finished:
            break
        messages.append(Message("user", tool_results=results))
    return Exchange(
        calls.checked,
        "\n\n".join(texts),
        usage,
        tuple(messages),
        tuple(calls.rejections),
    )


def _reason(error: ValidationError | RejectedDecisionError) -> str:
    if isinstance(error, RejectedDecisionError):
        return str(error)
    lines = [
        f"- {'.'.join(str(part) for part in item['loc']) or 'decision'}: {item['msg']}"
        for item in error.errors(include_url=False)
    ]
    return (
        "The decision is not valid:\n"
        + "\n".join(lines)
        + "\nCorrect it and call submit_decision again."
    )
