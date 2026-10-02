"""A run of the large-scale optimizer followed closely (after the piloted bracket)."""

from dataclasses import replace
from types import SimpleNamespace

from pilot_samples import problem

from gemseo_claude_pilot.detectors import DetectorSettings
from gemseo_claude_pilot.detectors import algorithm_events
from gemseo_claude_pilot.pilot import DECISION_EXPIRY_ITERATIONS
from gemseo_claude_pilot.pilot import _Run
from gemseo_claude_pilot.triggers import Triggers
from gemseo_claude_pilot.triggers import TriggerSettings


def reports(objectives, violations=None):
    violations = violations or [-1.0] * len(objectives)
    return tuple(
        {
            "iteration": index + 1,
            "method": "gcmma",
            "objective": objective,
            "max_constraint": violation,
            "kkt_residual": 0.01,
            "working_set": 10,
            "rows_computed": 10,
            "rows_reused": 0,
            "screening_repairs": 0,
            "inner_iterations": 3,
            "step": 0.1,
            "restoration": 0,
        }
        for index, (objective, violation) in enumerate(
            zip(objectives, violations, strict=True)
        )
    )


def kinds(objectives, violations=None):
    snapshot = replace(problem(), algorithm_state=reports(objectives, violations))
    return [event.kind for event in algorithm_events(snapshot, DetectorSettings(), 99)]


def test_the_first_call_after_the_first_outer_iteration():
    triggers = Triggers(TriggerSettings(period=None, min_interval=0))
    assert triggers.due(1, [], iteration=0) == (None, [])  # The starting point.
    assert triggers.due(3, [], iteration=1) == ("periodic", [])
    assert triggers.due(4, [], iteration=2) == (None, [])  # Not answered yet.


def test_a_call_every_ten_outer_iterations():
    settings = TriggerSettings(
        period=None, launch_pause=None, first_iteration=False, min_interval=0
    )
    triggers = Triggers(settings)
    # GCMMA makes several evaluations per outer iteration: they do not count.
    assert triggers.due(30, [], iteration=9) == (None, [])
    assert triggers.due(33, [], iteration=10) == ("periodic", [])
    assert triggers.due(60, [], iteration=19) == (None, [])
    assert triggers.due(63, [], iteration=20) == ("periodic", [])


def test_a_call_at_the_end_of_an_iteration_two_minutes_after_the_last_launch():
    now = [0.0]
    settings = TriggerSettings(period=None, first_iteration=False, min_interval=0)
    triggers = Triggers(settings, clock=lambda: now[0])
    # Never launched: the end of the first iteration calls Claude.
    assert triggers.due(3, [], iteration=1) == ("periodic", [])
    now[0] = 119.0  # A call that ended 119 s after its start.
    assert triggers.due(6, [], iteration=2) == (None, [])
    now[0] = 120.0
    assert triggers.due(9, [], iteration=3) == ("periodic", [])
    # The next outer iteration only: not twice in the same one.
    now[0] = 250.0
    assert triggers.due(10, [], iteration=3) == (None, [])
    assert triggers.due(12, [], iteration=4) == ("periodic", [])


def test_fast_iterations_call_every_ten_of_them_within_two_minutes():
    now = [0.0]
    settings = TriggerSettings(period=None, first_iteration=False, min_interval=0)
    triggers = Triggers(settings, clock=lambda: now[0])
    assert triggers.due(3, [], iteration=1)[0] == "periodic"
    for iteration in range(2, 11):
        now[0] += 1.0
        assert triggers.due(3 * iteration, [], iteration=iteration)[0] is None
    now[0] += 1.0  # 10 s after the call, 10 iterations later.
    assert triggers.due(33, [], iteration=11)[0] == "periodic"


def test_a_plateau_of_the_objective():
    assert "plateau" in kinds([0.5] * 5 + [0.3405 - 1e-4 * i for i in range(20)])
    assert "plateau" not in kinds([0.5 * 0.95**i for i in range(25)])
    assert "plateau" not in kinds([0.34] * 10)  # Too early to tell.


def test_a_decreasing_violation_is_not_stuck():
    objectives = [0.5 * 0.95**i for i in range(25)]
    decreasing = [0.1 * 0.8**i for i in range(25)]
    assert "stuck" not in kinds(objectives, decreasing)
    assert "stuck" in kinds(objectives, [0.01] * 25)


def test_a_decision_on_an_lso_algorithm_expires_in_iterations():
    run = object.__new__(_Run)
    run.reports = [{"iteration": 30}]
    run.problem = SimpleNamespace(database=[None] * 500)
    # 400 evaluations but 5 outer iterations ago: still fresh.
    assert run._age(100, 25) == (5, False)
    assert run._age(100, 30 - DECISION_EXPIRY_ITERATIONS - 1) == (11, True)
    # Without reports, in evaluations.
    run.reports = []
    assert run._age(480, -1) == (20, False)
