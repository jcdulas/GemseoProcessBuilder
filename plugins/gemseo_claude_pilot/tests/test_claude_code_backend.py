import asyncio

import pytest
from claude_agent_sdk import AssistantMessage
from claude_agent_sdk import CLINotFoundError
from claude_agent_sdk import ResultMessage
from claude_agent_sdk import TextBlock
from mcp.types import CallToolRequest
from mcp.types import CallToolRequestParams
from pilot_samples import history
from pilot_samples import problem

from gemseo_claude_pilot.backends import AuthenticationError
from gemseo_claude_pilot.backends import BackendError
from gemseo_claude_pilot.backends import BackendTimeoutError
from gemseo_claude_pilot.backends import BackendUnavailableError
from gemseo_claude_pilot.backends import RateLimitError
from gemseo_claude_pilot.backends import Request
from gemseo_claude_pilot.backends import ToolResult
from gemseo_claude_pilot.backends.claude_code import ClaudeCodeBackend
from gemseo_claude_pilot.backends.claude_code import login_status
from gemseo_claude_pilot.context import build_context
from gemseo_claude_pilot.context import render
from gemseo_claude_pilot.exchange import exchange
from gemseo_claude_pilot.guardrails import Limits
from gemseo_claude_pilot.guardrails import check
from gemseo_claude_pilot.prompts import system_prompt
from gemseo_claude_pilot.tools import TOOLS

SNAPSHOT = problem()


def result_message(is_error=False):
    return ResultMessage(
        subtype="error" if is_error else "success",
        duration_ms=10,
        duration_api_ms=8,
        is_error=is_error,
        num_turns=2,
        session_id="session",
        usage={
            "input_tokens": 100,
            "output_tokens": 40,
            "cache_creation_input_tokens": 10,
            "cache_read_input_tokens": 500,
        },
        result="out of credits" if is_error else "done",
    )


def assistant(text="", error=None):
    return AssistantMessage(content=[TextBlock(text=text)], model="m", error=error)


async def call_tool(options, name, arguments):
    """Call a tool of the pilot's MCP server, as Claude Code does."""
    server = options.mcp_servers["pilot"]["instance"]
    handler = server.request_handlers[CallToolRequest]
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=arguments),
    )
    return (await handler(request)).root


def narrow(upper):
    return {
        "diagnosis": "Near the lower bounds.",
        "action": {
            "kind": "change_design_space",
            "variables": [{"name": "x", "upper": upper}],
        },
    }


def test_the_options_lock_claude_code_down():
    backend = ClaudeCodeBackend()
    request = Request("the system prompt", (), "claude-sonnet-5", TOOLS)
    options = backend.options(request, lambda call: ToolResult(call.id, ""))
    assert options.tools == []
    assert options.setting_sources == []
    assert options.permission_mode == "dontAsk"
    assert options.strict_mcp_config is True
    assert options.env == {"ANTHROPIC_API_KEY": ""}
    assert options.system_prompt == "the system prompt"
    assert options.model == "claude-sonnet-5"
    assert options.effort is None  # The model's default.
    assert options.allowed_tools == [f"mcp__pilot__{tool.name}" for tool in TOOLS]
    assert list(options.mcp_servers) == ["pilot"]
    assert not any(options.cwd.iterdir())


def test_a_refused_decision_then_a_corrected_one():
    answers = []

    async def query(prompt, options):
        assert prompt.startswith('{"trigger"')
        answers.append(await call_tool(options, "get_constraint", {"name": "g"}))
        answers.append(await call_tool(options, "submit_decision", narrow(20)))
        answers.append(await call_tool(options, "submit_decision", narrow(4)))
        yield assistant("Narrowed x.")
        yield result_message()

    result = exchange(
        ClaudeCodeBackend(query=query),
        system_prompt(),
        "claude-sonnet-5",
        render(build_context(SNAPSHOT, history([3.0, 2.0]))),
        lambda made: check(made, SNAPSHOT, Limits.of(SNAPSHOT), 10),
    )

    unavailable, refused, recorded = answers
    assert unavailable.isError
    assert refused.isError
    assert "go beyond the ones the user set" in refused.content[0].text
    assert not recorded.isError
    assert recorded.content[0].text.startswith("Decision recorded.")
    assert result.checked.decision.action.variables[0].upper == 4
    assert result.text == "Narrowed x."
    assert result.usage.input_tokens == 110
    assert result.usage.cached_tokens == 500
    assert result.usage.cost_usd == 0.0


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (assistant(error="authentication_failed"), AuthenticationError),
        (assistant(error="billing_error"), AuthenticationError),
        (assistant(error="rate_limit"), RateLimitError),
        (assistant(error="server_error"), BackendError),
        (result_message(is_error=True), BackendError),
    ],
)
def test_errors_of_claude_code(message, expected):
    async def query(prompt, options):
        yield message

    backend = ClaudeCodeBackend(query=query)
    with pytest.raises(expected):
        backend.converse(Request("s", (), "m", TOOLS), lambda call: None)


def test_claude_code_not_installed():
    async def query(prompt, options):
        raise CLINotFoundError("no claude")
        yield  # An async generator.

    backend = ClaudeCodeBackend(query=query)
    with pytest.raises(BackendUnavailableError, match="not installed"):
        backend.converse(Request("s", (), "m", TOOLS), lambda call: None)


def test_timeout():
    async def query(prompt, options):
        await asyncio.sleep(1)
        yield result_message()

    backend = ClaudeCodeBackend(timeout=0.05, query=query)
    with pytest.raises(BackendTimeoutError):
        backend.converse(Request("s", (), "m", TOOLS), lambda call: None)


def test_login_status():
    logged_in = login_status(
        '{"loggedIn": true, "authMethod": "claude.ai", "subscriptionType": "max",'
        ' "email": "someone@example.com"}'
    )
    assert logged_in.ok
    assert logged_in.message == "Claude Code is logged in (max subscription)."
    assert "someone" not in logged_in.message
    assert not login_status('{"loggedIn": false}').ok
    assert not login_status("Error: something").ok


def test_check_without_claude_code(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    status = ClaudeCodeBackend().check()
    assert not status.ok
    assert status.message.startswith("Claude Code is not installed")


def test_claude_code_gets_the_effort():
    request = Request("system", (), "claude-opus-5-5", TOOLS, effort="low")
    options = ClaudeCodeBackend().options(request, lambda call: ToolResult(call.id, ""))
    assert options.effort == "low"


def test_a_short_system_prompt_is_given_as_text_and_a_long_one_as_a_file():
    from gemseo_claude_pilot.prompts import system_prompt

    backend = ClaudeCodeBackend()
    handle = lambda call: ToolResult(call.id, "")  # noqa: E731
    short = backend.options(Request("short", (), "claude-sonnet-5", TOOLS), handle)
    assert short.system_prompt == "short"
    # The current prompt is longer than a Windows command line can hold.
    text = system_prompt()
    long = backend.options(Request(text, (), "claude-sonnet-5", TOOLS), handle)
    assert len(text) > 20_000
    assert long.system_prompt["type"] == "file"
    with open(long.system_prompt["path"], encoding="utf-8") as file:
        assert file.read() == text
    # The same prompt is the same file: written once.
    again = backend.options(Request(text, (), "claude-sonnet-5", TOOLS), handle)
    assert again.system_prompt == long.system_prompt
    assert not any(long.cwd.iterdir())  # The working folder stays empty.
