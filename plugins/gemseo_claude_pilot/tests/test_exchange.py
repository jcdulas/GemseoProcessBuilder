import pytest
from pilot_samples import history
from pilot_samples import problem

from gemseo_claude_pilot.backends import BackendError
from gemseo_claude_pilot.backends import FakeBackend
from gemseo_claude_pilot.backends import RateLimitError
from gemseo_claude_pilot.backends import Usage
from gemseo_claude_pilot.backends.fake import Delayed
from gemseo_claude_pilot.context import build_context
from gemseo_claude_pilot.context import render
from gemseo_claude_pilot.exchange import exchange
from gemseo_claude_pilot.guardrails import Limits
from gemseo_claude_pilot.guardrails import check
from gemseo_claude_pilot.privacy import Anonymizer
from gemseo_claude_pilot.prompts import system_prompt

SNAPSHOT = problem()
LIMITS = Limits.of(SNAPSHOT)


def checker(decision):
    return check(decision, SNAPSHOT, LIMITS, evaluations_used=10)


def narrow(upper, name="x"):
    return {
        "diagnosis": "The optimum is near the lower bounds.",
        "action": {
            "kind": "change_design_space",
            "variables": [{"name": name, "upper": upper}],
        },
    }


def run(script, **options):
    backend = FakeBackend(script)
    context = render(build_context(SNAPSHOT, history([3.0, 2.0, 1.0])))
    result = exchange(backend, system_prompt(), "a-model", context, checker, **options)
    return backend, result


def test_rejected_decision_sent_back_then_corrected():
    backend, result = run(
        [FakeBackend.decision(narrow(20)), FakeBackend.decision(narrow(4))]
    )

    first, second = backend.requests
    assert first.system == system_prompt()
    assert first.model == "a-model"
    assert '"trigger": "periodic"' in first.messages[0].text
    assert [tool.name for tool in first.tools][-1] == "submit_decision"
    feedback = second.messages[-1].tool_results[0]
    assert feedback.is_error
    assert "the bounds of x go beyond the ones the user set" in feedback.content

    assert result.checked.decision.action.variables[0].upper == 4
    assert result.rejections == (feedback.content,)
    assert result.usage == Usage(input_tokens=2000, output_tokens=200)


def test_two_rejections_end_without_decision():
    backend, result = run(
        [FakeBackend.decision(narrow(20)), FakeBackend.decision(narrow(30))]
    )
    assert result.checked is None
    assert len(result.rejections) == 2
    assert len(backend.requests) == 2


def test_invalid_decision_is_explained():
    _, result = run(
        [
            FakeBackend.decision({"diagnosis": "d", "action": {"kind": "restart"}}),
            FakeBackend.decision({"diagnosis": "d"}),
        ]
    )
    assert result.rejections[0].startswith("The decision is not valid:")
    assert result.checked.decision.action.kind == "none"


def test_read_tools_without_handler():
    backend, result = run(
        [
            FakeBackend.tool(("get_constraint", {"name": "g"})),
            FakeBackend.decision({"diagnosis": "d"}),
        ]
    )
    answer = backend.requests[1].messages[-1].tool_results[0]
    assert answer.is_error
    assert answer.content == "The tool get_constraint is not available."
    assert result.checked is not None


def test_read_tools_with_a_handler():
    def answer_tool(call):
        if call.input["name"] == "broken":
            raise KeyError(call.input["name"])
        return f"{call.input['name']} is fine"

    backend, _ = run(
        [
            FakeBackend.tool(
                ("get_constraint", {"name": "g"}),
                ("get_constraint", {"name": "broken"}),
            ),
            FakeBackend.decision({"diagnosis": "d"}),
        ],
        answer_tool=answer_tool,
    )
    fine, broken = backend.requests[1].messages[-1].tool_results
    assert (fine.content, fine.is_error) == ("g is fine", False)
    assert broken.is_error
    assert broken.content == "The tool get_constraint failed: 'broken'"


def test_too_many_tool_calls():
    calls = [FakeBackend.tool(("list_algorithms", {})) for _ in range(3)]
    backend, result = run(
        [*calls, FakeBackend.decision({"diagnosis": "d"})], max_tool_calls=2
    )
    last = backend.requests[3].messages[-1].tool_results[0]
    assert last.content == "Too many tool calls: submit your decision now."
    assert result.checked is not None


def test_answer_in_words():
    _, result = run([FakeBackend.text("The run converges.")])
    assert result.checked is None
    assert result.text == "The run converges."


def test_backend_errors():
    with pytest.raises(RateLimitError) as error:
        run([RateLimitError("Slow down.")])
    assert error.value.retryable
    with pytest.raises(BackendError, match="no more answers"):
        run([FakeBackend.tool(("list_algorithms", {}))])


def test_delayed_answer():
    _, result = run([Delayed(0.01, FakeBackend.decision({"diagnosis": "d"}))])
    assert result.checked is not None


def test_anonymized_exchange():
    anonymizer = Anonymizer(SNAPSHOT)
    context = build_context(
        SNAPSHOT, history([3.0, 2.0]), level="anonymized", anonymizer=anonymizer
    )
    backend = FakeBackend(
        [
            # Claude only knows "x1": the real name "x" is refused.
            FakeBackend.decision(narrow(0.4)),
            FakeBackend.decision({**narrow(0.4, name="x1"), "diagnosis": "x1 is low."}),
        ]
    )
    result = exchange(
        backend,
        system_prompt(),
        "a-model",
        render(context),
        lambda decision: checker(anonymizer.decision(decision)),
    )
    assert "there is no design variable named x" in result.rejections[0]
    assert result.checked.decision.action.variables[0].upper == [4.0, 4.0]
    assert result.checked.decision.diagnosis == "x is low."
