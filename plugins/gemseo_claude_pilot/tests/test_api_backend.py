from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from pilot_samples import history
from pilot_samples import problem

from gemseo_claude_pilot.advisor import Models
from gemseo_claude_pilot.backends import AuthenticationError
from gemseo_claude_pilot.backends import BackendError
from gemseo_claude_pilot.backends import BackendTimeoutError
from gemseo_claude_pilot.backends import RateLimitError
from gemseo_claude_pilot.backends import Request
from gemseo_claude_pilot.backends.api import ApiKeyBackend
from gemseo_claude_pilot.backends.api import request_parameters
from gemseo_claude_pilot.context import build_context
from gemseo_claude_pilot.context import render
from gemseo_claude_pilot.exchange import exchange
from gemseo_claude_pilot.guardrails import Limits
from gemseo_claude_pilot.guardrails import check
from gemseo_claude_pilot.pricing import estimate_cost
from gemseo_claude_pilot.prompts import system_prompt

SNAPSHOT = problem()
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


class Messages:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def create(self, **parameters):
        self.calls.append(parameters)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def response(*blocks, stop_reason="tool_use"):
    return SimpleNamespace(
        content=list(blocks),
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=1000,
            cache_read_input_tokens=0,
        ),
        stop_reason=stop_reason,
    )


def decision(upper, call_id):
    return SimpleNamespace(
        type="tool_use",
        id=call_id,
        name="submit_decision",
        input={
            "diagnosis": "Near the lower bounds.",
            "action": {
                "kind": "change_design_space",
                "variables": [{"name": "x", "upper": upper}],
            },
        },
    )


def backend(*answers):
    client = SimpleNamespace(messages=Messages(answers))
    return ApiKeyBackend(client=client), client.messages


def test_a_refused_decision_then_a_corrected_one():
    thinking = SimpleNamespace(type="thinking", thinking="", signature="s")
    api, messages = backend(
        response(thinking, decision(20, "toolu_1")),
        response(
            SimpleNamespace(type="text", text="Narrower then."),
            decision(4, "toolu_2"),
        ),
    )
    context = render(build_context(SNAPSHOT, history([3.0, 2.0])))
    result = exchange(
        api,
        system_prompt(),
        "claude-sonnet-5",
        context,
        lambda made: check(made, SNAPSHOT, Limits.of(SNAPSHOT), 10),
    )

    first, second = messages.calls
    assert first["model"] == "claude-sonnet-5"
    assert "output_config" not in first  # The model's default effort.
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["tools"][-1]["name"] == "submit_decision"
    assert first["messages"] == [{"role": "user", "content": context}]
    assistant, results = second["messages"][1:]
    assert assistant["content"][0] is thinking  # Sent back as received.
    assert results["content"][0]["tool_use_id"] == "toolu_1"
    assert results["content"][0]["is_error"] is True
    assert result.checked.decision.action.variables[0].upper == 4
    assert result.text == "Narrower then."
    assert result.usage.input_tokens == 2 * 1100
    assert result.usage.cost_usd == pytest.approx(
        2 * estimate_cost("claude-sonnet-5", 100, 50, 1000)
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            anthropic.AuthenticationError(
                "bad key", response=httpx2.Response(401, request=REQUEST), body=None
            ),
            AuthenticationError,
        ),
        (
            anthropic.RateLimitError(
                "slow down", response=httpx2.Response(429, request=REQUEST), body=None
            ),
            RateLimitError,
        ),
        (anthropic.APITimeoutError(request=REQUEST), BackendTimeoutError),
        (anthropic.APIConnectionError(request=REQUEST), BackendError),
        (
            anthropic.InternalServerError(
                "boom", response=httpx2.Response(500, request=REQUEST), body=None
            ),
            BackendError,
        ),
    ],
)
def test_errors(error, expected):
    api, _ = backend(error)
    with pytest.raises(expected):
        api.send(Request("system", (), "claude-sonnet-5"))


def test_without_key(monkeypatch):
    monkeypatch.setattr("gemseo_claude_pilot.backends.api.api_key", lambda: None)
    api = ApiKeyBackend()
    assert not api.check().ok
    with pytest.raises(AuthenticationError, match="No API key"):
        api.send(Request("system", (), "claude-sonnet-5"))


def test_with_key():
    assert ApiKeyBackend(key="sk-test").check().ok


def test_cost_of_an_unknown_model_is_zero():
    assert estimate_cost("claude-unknown", 10**6, 10**6) == 0.0
    assert estimate_cost("claude-haiku-4-5", 10**6, 10**6) == pytest.approx(6.0)


def test_the_effort_of_a_call():
    request = Request("system", (), "claude-opus-5-5", effort="low")
    assert request_parameters(request, 1000)["output_config"] == {"effort": "low"}
    models = Models(watch="claude-haiku-4-5", decision="claude-opus-5-5", effort="low")
    assert models.effort_of("claude-opus-5-5") == "low"
    assert models.effort_of("claude-haiku-4-5") == ""  # Haiku takes no effort.
    assert Models(effort="huge").effort_of("claude-opus-5-5") == ""


def test_opus_at_a_low_effort_by_default(monkeypatch):
    for name in ("WATCH_MODEL", "DECISION_MODEL", "EFFORT"):
        monkeypatch.delenv(f"GEMSEO_CLAUDE_PILOT_{name}", raising=False)
    models = Models()
    assert (models.watch, models.decision, models.effort) == (
        "claude-opus-5-5",
        "claude-opus-5-5",
        "low",
    )
