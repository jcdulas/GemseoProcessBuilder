import numpy as np
from pilot_samples import history
from pilot_samples import problem

from gemseo_claude_pilot.detectors import DetectorSettings
from gemseo_claude_pilot.detectors import bounds
from gemseo_claude_pilot.detectors import detect
from gemseo_claude_pilot.detectors import divergence
from gemseo_claude_pilot.detectors import failed_evaluations
from gemseo_claude_pilot.detectors import infeasibility
from gemseo_claude_pilot.detectors import oscillation
from gemseo_claude_pilot.detectors import stagnation

SETTINGS = DetectorSettings()


def test_stagnation():
    improving = history(list(np.linspace(10, 1, 40)))
    assert stagnation(improving, SETTINGS) is None
    flat = history([10, 5, 2, *[1.0] * 30])
    event = stagnation(flat, SETTINGS)
    assert event is not None
    assert event.kind == "stagnation"
    assert event.index == 32


def test_stagnation_on_a_maximization():
    rising = history(list(np.linspace(1, 10, 40)), minimize=False)
    assert stagnation(rising, SETTINGS) is None


def test_no_stagnation_without_enough_evaluations():
    assert stagnation(history([1.0] * 20), SETTINGS) is None


def test_infeasibility():
    infeasible = history([1.0] * 40, violation=[0.5] * 40)
    event = infeasibility(infeasible, SETTINGS)
    assert event is not None
    assert "smallest violation is 0.5" in event.message
    feasible_at_the_end = history([1.0] * 40, violation=[0.5] * 39 + [0.0])
    assert infeasibility(feasible_at_the_end, SETTINGS) is None


def test_divergence_of_the_objective():
    assert divergence(history(list(range(12))), SETTINGS).message == (
        "The objective has kept growing over the last 10 evaluations."
    )
    assert divergence(history(list(range(12, 0, -1))), SETTINGS) is None


def test_divergence_of_the_violation():
    event = divergence(history([1.0] * 12, violation=list(range(12))), SETTINGS)
    assert "constraint violation" in event.message


def test_failed_evaluations():
    failing = history([1.0, np.nan, 2.0, np.inf])
    event = failed_evaluations(failing)
    assert event.message.startswith("2 evaluation(s) failed")
    assert "(evaluations 1, 3)" in event.message
    assert failed_evaluations(failing, since=4) is None


def test_oscillation():
    points = [[0.5 + (-1) ** i * 0.2 / (i + 1), 0.5] for i in range(6)]
    assert (
        oscillation(history([1.0] * 6, recent_x=points), SETTINGS).kind == "oscillation"
    )
    straight = [[0.1 * i, 0.5] for i in range(6)]
    assert oscillation(history([1.0] * 6, recent_x=straight), SETTINGS) is None


def test_bounds():
    at_bounds = history([1.0], recent_x=[[0.0, 1.0]])
    assert bounds(at_bounds, problem(), SETTINGS).message == (
        "100% of the design components are at one of their bounds."
    )
    inside = history([1.0], recent_x=[[0.0, 0.5]])
    assert bounds(inside, problem(), SETTINGS) is None


def test_detect_a_healthy_run():
    assert detect(history(list(np.linspace(10, 1, 40))), problem()) == []
