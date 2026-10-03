"""The Claude Code backend, the default: the user's own Claude Code (spec § 5.1).

Through ``claude-agent-sdk``, which drives the Claude Code CLI installed and
logged in by the user. Claude Code runs the loop of tool calls itself; the
pilot's tools are served in process by an MCP server and answered by the
exchange. Claude Code is locked down:

- none of its built-in tools (no shell, no files, no web);
- only the pilot's tools, pre-approved; any other tool is refused;
- no user, project or local settings, in an empty working folder;
- ``ANTHROPIC_API_KEY`` blanked, so that the subscription login is used.

The plugin never handles a token: authentication is Claude Code's.
"""

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import AsyncIterator
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gemseo_claude_pilot.backends.base import AuthenticationError
from gemseo_claude_pilot.backends.base import BackendError
from gemseo_claude_pilot.backends.base import BackendStatus
from gemseo_claude_pilot.backends.base import BackendTimeoutError
from gemseo_claude_pilot.backends.base import BackendUnavailableError
from gemseo_claude_pilot.backends.base import RateLimitError
from gemseo_claude_pilot.backends.base import Reply
from gemseo_claude_pilot.backends.base import Request
from gemseo_claude_pilot.backends.base import ToolCall
from gemseo_claude_pilot.backends.base import ToolCallHandler
from gemseo_claude_pilot.backends.base import ToolSpec
from gemseo_claude_pilot.backends.base import Usage

SERVER = "pilot"
"""The name of the MCP server of the pilot's tools."""

LONG_SYSTEM_PROMPT = 20_000
"""Characters of a system prompt above which it is given to Claude Code in a file.

The CLI takes it as an argument, and a command line is limited to about 32,000
characters on Windows: the prompt of version 18 (33,000) made the creation of the
process fail, which the SDK reports as a CLI that is not installed."""

MAX_TURNS = 14
"""Turns of Claude in one conversation: the read tools, a decision, a correction."""

NOT_INSTALLED = (
    "Claude Code is not installed: install it (https://code.claude.com) and "
    "log in with `claude` in a terminal, or choose the API key backend."
)
NOT_LOGGED_IN = (
    "Claude Code is not logged in: run `claude` in a terminal and log in with "
    "your Claude account, or choose the API key backend."
)

Query = Callable[..., AsyncIterator[Any]]
"""The ``query`` function of ``claude-agent-sdk``."""


class ClaudeCodeBackend:
    """Talks to Claude through the user's Claude Code.

    Args:
        timeout: The seconds a whole conversation may take.
        cli_path: The Claude Code executable; found on the path by default.
        query: The ``query`` function of ``claude-agent-sdk``, for the tests.
    """

    name = "claude_code"

    def __init__(
        self,
        timeout: float = 180.0,
        cli_path: str | Path | None = None,
        query: Query | None = None,
    ) -> None:
        self._timeout = timeout
        self._cli_path = cli_path
        self._query = query

    def check(self) -> BackendStatus:
        """Whether Claude Code is installed and logged in (``claude auth status``)."""
        executable = str(self._cli_path or shutil.which("claude") or "")
        if not executable:
            return BackendStatus(False, NOT_INSTALLED)
        try:
            completed = subprocess.run(
                [executable, "auth", "status"],
                capture_output=True,
                text=True,
                timeout=30,
                env=_environment(),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return BackendStatus(False, f"Claude Code did not answer: {error}")
        return login_status(completed.stdout)

    def converse(self, request: Request, handle: ToolCallHandler) -> Reply:
        """Run the conversation in Claude Code, answering its tool calls.

        Raises:
            BackendError: When the conversation fails.
        """
        try:
            return asyncio.run(
                asyncio.wait_for(self._converse(request, handle), self._timeout)
            )
        except TimeoutError as error:
            raise BackendTimeoutError("Claude Code did not answer in time.") from error
        except BackendError:
            raise
        except ImportError as error:
            raise BackendUnavailableError(
                f"The claude-agent-sdk package is missing: {error}"
            ) from error
        except Exception as error:
            from claude_agent_sdk import CLINotFoundError

            if isinstance(error, CLINotFoundError):
                raise BackendUnavailableError(NOT_INSTALLED) from error
            raise BackendError(f"Claude Code failed: {error}") from error

    async def _converse(self, request: Request, handle: ToolCallHandler) -> Reply:
        from claude_agent_sdk import AssistantMessage
        from claude_agent_sdk import ResultMessage
        from claude_agent_sdk import TextBlock
        from claude_agent_sdk import query

        run = self._query or query
        texts: list[str] = []
        usage = Usage()
        prompt = request.messages[-1].text if request.messages else ""
        async for message in run(prompt=prompt, options=self.options(request, handle)):
            if isinstance(message, AssistantMessage):
                if message.error:
                    raise _assistant_error(message.error)
                texts += [
                    block.text
                    for block in message.content
                    if isinstance(block, TextBlock)
                ]
            elif isinstance(message, ResultMessage):
                usage = _usage(message.usage or {})
                if message.is_error:
                    detail = message.result or ""
                    raise BackendError(
                        f"Claude Code failed ({message.subtype}): {detail}"
                    )
        return Reply(text="\n\n".join(texts), usage=usage)

    def options(self, request: Request, handle: ToolCallHandler) -> Any:
        """The options of Claude Code for a conversation with the pilot's tools."""
        from claude_agent_sdk import ClaudeAgentOptions
        from claude_agent_sdk import create_sdk_mcp_server

        server = create_sdk_mcp_server(
            name=SERVER, tools=[sdk_tool(spec, handle) for spec in request.tools]
        )
        return ClaudeAgentOptions(
            system_prompt=_system_prompt(request.system),
            model=request.model,
            effort=request.effort or None,
            tools=[],
            mcp_servers={SERVER: server},
            strict_mcp_config=True,
            allowed_tools=[tool_name(spec) for spec in request.tools],
            permission_mode="dontAsk",
            setting_sources=[],
            max_turns=MAX_TURNS,
            cwd=_empty_folder(),
            cli_path=self._cli_path,
            env={"ANTHROPIC_API_KEY": ""},
        )


def tool_name(spec: ToolSpec) -> str:
    """The name Claude Code gives to a tool of the pilot's MCP server."""
    return f"mcp__{SERVER}__{spec.name}"


def sdk_tool(spec: ToolSpec, handle: ToolCallHandler) -> Any:
    """A tool of the pilot for the in-process MCP server, answered by ``handle``."""
    from claude_agent_sdk import tool

    calls = 0

    async def answer(arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        result = handle(ToolCall(f"{spec.name}_{calls}", spec.name, arguments))
        return {
            "content": [{"type": "text", "text": result.content}],
            "is_error": result.is_error,
        }

    return tool(spec.name, spec.description, dict(spec.input_schema))(answer)


def login_status(output: str) -> BackendStatus:
    """The status of the login, from the output of ``claude auth status``."""
    try:
        status = json.loads(output)
    except json.JSONDecodeError:
        return BackendStatus(False, f"Unexpected answer of Claude Code: {output[:200]}")
    if not status.get("loggedIn"):
        return BackendStatus(False, NOT_LOGGED_IN)
    method = status.get("authMethod", "unknown")
    subscription = status.get("subscriptionType")
    detail = f"{subscription} subscription" if subscription else method
    return BackendStatus(True, f"Claude Code is logged in ({detail}).")


def _environment() -> dict[str, str]:
    """The environment of Claude Code, without an API key that would win."""
    return {**os.environ, "ANTHROPIC_API_KEY": ""}


def _system_prompt(text: str) -> Any:
    """The system prompt, or the file holding it when it is too long for a command line.

    The file is named after its content: a prompt is written once.
    """
    if len(text) <= LONG_SYSTEM_PROMPT:
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    folder = Path(tempfile.gettempdir()) / "gemseo-claude-pilot-prompts"
    folder.mkdir(exist_ok=True)
    path = folder / f"system_{digest}.md"
    if not path.is_file():
        path.write_text(text, encoding="utf-8")
    return {"type": "file", "path": str(path)}


def _empty_folder() -> Path:
    """A working folder without any project file for Claude Code to read."""
    folder = Path(tempfile.gettempdir()) / "gemseo-claude-pilot"
    folder.mkdir(exist_ok=True)
    return folder


def _usage(usage: dict[str, Any]) -> Usage:
    written = int(usage.get("cache_creation_input_tokens") or 0)
    return Usage(
        input_tokens=int(usage.get("input_tokens") or 0) + written,
        output_tokens=int(usage.get("output_tokens") or 0),
        cached_tokens=int(usage.get("cache_read_input_tokens") or 0),
    )


def _assistant_error(kind: str) -> BackendError:
    if kind in ("authentication_failed", "billing_error"):
        return AuthenticationError(f"Claude Code refused the login ({kind}).")
    if kind == "rate_limit":
        return RateLimitError("The usage limits of the subscription are reached.")
    return BackendError(f"Claude Code failed ({kind}).")
