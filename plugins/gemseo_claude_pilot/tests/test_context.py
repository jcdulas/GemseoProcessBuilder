import json

import numpy as np
import pytest
from pilot_samples import history
from pilot_samples import problem
from pilot_samples import sellar

from gemseo_claude_pilot.context import PastDecision
from gemseo_claude_pilot.context import build_context
from gemseo_claude_pilot.context import estimate_tokens
from gemseo_claude_pilot.context import render
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.detectors import Event
from gemseo_claude_pilot.snapshots import Component
from gemseo_claude_pilot.snapshots import snapshot_history
from gemseo_claude_pilot.snapshots import snapshot_problem


def sellar_snapshots(components=()):
    problem = sellar().formulation.optimization_problem
    snapshot = snapshot_problem(problem, "SLSQP", 100, components=components)
    return snapshot, snapshot_history(problem, snapshot)


def test_context_of_sellar():
    snapshot, sellar_history = sellar_snapshots()
    context = build_context(snapshot, sellar_history, trigger="start")
    assert context["trigger"] == "start"
    section = context["problem"]
    assert section["objective"] == {"name": "obj", "direction": "minimize"}
    assert [item["name"] for item in section["design_variables"]] == [
        "x_1",
        "x_2",
        "x_shared",
    ]
    assert section["design_variables"][2]["upper"] == [10.0, 10.0]
    states = {item["name"]: item["state_at_best"] for item in section["constraints"]}
    assert set(states.values()) <= {"active", "inactive", "violated"}
    assert context["state"]["evaluations"] == sellar_history.n_evaluations
    assert len(context["history"]["recent"]) == sellar_history.n_evaluations
    assert json.loads(render(context)) == context


def test_events_decisions_and_question():
    context = build_context(
        problem(),
        history([3.0, 2.0, 1.0]),
        trigger="question",
        events=[Event("stagnation", "Nothing moves.", 2)],
        decisions=[PastDecision(1, Decision(diagnosis="Fine."), "It went on.")],
        question="Why so slow?",
    )
    assert context["events"] == [
        {"kind": "stagnation", "evaluation": 2, "message": "Nothing moves."}
    ]
    assert context["decisions"] == [
        {
            "evaluation": 1,
            "decision": {"diagnosis": "Fine.", "action": {"kind": "none"}},
            "outcome": "It went on.",
        }
    ]
    assert context["question"] == "Why so slow?"


def test_long_history_is_compressed():
    long_history = history(list(np.linspace(100, 1, 5000)))
    context = build_context(problem(), long_history, target_tokens=3000)
    assert estimate_tokens(render(context)) <= 3000
    windows = context["history"]["earlier"]
    assert windows[0]["evaluations"][1] - windows[0]["evaluations"][0] + 1 > 20
    assert context["history"]["recent"][-1]["evaluation"] == 4999


def test_short_history_keeps_windows_of_twenty():
    context = build_context(problem(), history(list(np.linspace(100, 1, 100))))
    assert [window["evaluations"] for window in context["history"]["earlier"]] == [
        [0, 19],
        [20, 39],
        [40, 59],
        [60, 79],
    ]


def test_components_without_their_source():
    component = Component(
        "Sellar1", "The first discipline.", ("x_1",), ("y_1",), "SOURCE"
    )
    snapshot, sellar_history = sellar_snapshots((component,))
    for level in ("full", "no_code"):
        context = build_context(snapshot, sellar_history, level=level)
        assert context["problem"]["components"][0]["name"] == "Sellar1"
        assert "SOURCE" not in render(context)


def test_anonymized_needs_the_anonymizer():
    with pytest.raises(ValueError, match="needs the anonymizer"):
        build_context(problem(), history([1.0]), level="anonymized")
