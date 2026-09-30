import numpy as np
import pytest
from pilot_samples import sellar

from gemseo_claude_pilot.context import PastDecision
from gemseo_claude_pilot.context import build_context
from gemseo_claude_pilot.context import render
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.detectors import Event
from gemseo_claude_pilot.guardrails import RejectedDecisionError
from gemseo_claude_pilot.privacy import Anonymizer
from gemseo_claude_pilot.privacy import component_view
from gemseo_claude_pilot.snapshots import Component
from gemseo_claude_pilot.snapshots import snapshot_history
from gemseo_claude_pilot.snapshots import snapshot_problem

COMPONENT = Component(
    "Sellar1", "Couples x_1 to y_1.", ("x_1",), ("y_1",), "def f(): ..."
)

REAL_NAMES = ("x_1", "x_2", "x_shared", "obj", "c_1", "c_2", "Sellar1")


@pytest.fixture
def sellar_run():
    problem = sellar().formulation.optimization_problem
    snapshot = snapshot_problem(
        problem, "SLSQP", 100, formulation="MDF", components=(COMPONENT,)
    )
    return snapshot, snapshot_history(problem, snapshot)


def anonymized_decision(action):
    return Decision.model_validate(
        {"diagnosis": "x1 is at a bound; g1 is active.", "action": action}
    )


def test_anonymized_context_hides_names_and_values(sellar_run):
    snapshot, history = sellar_run
    anonymizer = Anonymizer(snapshot)
    context = build_context(
        snapshot,
        history,
        trigger="question",
        events=[Event("stagnation", "obj does not improve.", 3)],
        decisions=[
            PastDecision(
                2,
                Decision.model_validate(
                    {
                        "diagnosis": "x_1 is stuck.",
                        "action": {
                            "kind": "change_design_space",
                            "variables": [{"name": "x_1", "upper": 7.25}],
                        },
                    }
                ),
            )
        ],
        question="Why is c_1 active?",
        level="anonymized",
        anonymizer=anonymizer,
    )
    text = render(context)
    for name in REAL_NAMES:
        assert f'"{name}"' not in text
        assert f"{name} " not in text
    assert "7.25" not in text
    assert f"{history.objective[0]:.6g}" not in text
    assert f"{history.objective[history.best_index]:.6g}" not in text
    assert context["question"] == "Why is g1 active?"
    assert context["events"][0]["message"] == "f1 does not improve."
    assert context["decisions"][0]["decision"]["action"] == {
        "kind": "change_design_space"
    }
    variables = context["problem"]["design_variables"]
    assert [item["name"] for item in variables] == ["x1", "x2", "x3"]
    assert variables[2]["lower"] == [0.0, 0.0]
    assert variables[2]["upper"] == [1.0, 1.0]
    assert "components" not in context["problem"]


def test_scales_stay_the_same_from_one_call_to_the_next(sellar_run):
    snapshot, history = sellar_run
    anonymizer = Anonymizer(snapshot)
    first = anonymizer.history(history, snapshot)
    again = anonymizer.history(history, snapshot)
    assert np.allclose(first.objective, again.objective)
    assert first.objective[0] == pytest.approx(1.0)


def test_decision_translated_back(sellar_run):
    snapshot, _ = sellar_run
    anonymizer = Anonymizer(snapshot)
    decision = anonymizer.decision(
        anonymized_decision(
            {
                "kind": "change_design_space",
                "variables": [{"name": "x3", "lower": [0.1, 0.0], "upper": 0.5}],
            }
        )
    )
    change = decision.action.variables[0]
    assert change.name == "x_shared"
    assert change.lower == [-8.0, 0.0]
    assert change.upper == [0.0, 5.0]
    assert decision.diagnosis == "x_1 is at a bound; c_1 is active."


def test_decision_on_an_unknown_variable(sellar_run):
    snapshot, _ = sellar_run
    anonymizer = Anonymizer(snapshot)
    with pytest.raises(RejectedDecisionError, match="no design variable named x9"):
        anonymizer.decision(
            anonymized_decision(
                {
                    "kind": "change_design_space",
                    "variables": [{"name": "x9", "upper": 1}],
                }
            )
        )


def test_component_views():
    assert component_view(COMPONENT, "full")["source"] == "def f(): ..."
    assert "source" not in component_view(COMPONENT, "no_code")
    assert component_view(COMPONENT, "no_code")["outputs"] == ["y_1"]
    assert component_view(COMPONENT, "anonymized") is None
