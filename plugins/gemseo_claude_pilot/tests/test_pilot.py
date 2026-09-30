import time

import numpy as np
import pytest
from pilot_samples import rosenbrock

from gemseo_claude_pilot import ClaudePilot
from gemseo_claude_pilot.backends import AuthenticationError
from gemseo_claude_pilot.backends import BackendError
from gemseo_claude_pilot.backends import FakeBackend
from gemseo_claude_pilot.backends.fake import Delayed
from gemseo_claude_pilot.journal import read_journal
from gemseo_claude_pilot.triggers import TriggerSettings

FINE = FakeBackend.decision({"diagnosis": "The run is fine."})
"""The answer once a script is over."""

EVERY_THREE = TriggerSettings(period=3, min_interval=0, check_every=1, start=False)


def switch(algo_name="NLOPT_COBYLA"):
    return FakeBackend.decision(
        {
            "diagnosis": "SLSQP zigzags.",
            "action": {"kind": "switch_algorithm", "algo_name": algo_name},
            "rationale": "A derivative-free method is steadier here.",
        }
    )


def pilot(script, mode="pilot", triggers=EVERY_THREE, **options):
    backend = FakeBackend(script, then=options.pop("then", FINE))
    options.setdefault("journal", False)
    options.setdefault("threaded", False)
    return ClaudePilot(mode=mode, backend=backend, triggers=triggers, **options)


def test_without_backend_the_scenario_runs_as_is():
    scenario = rosenbrock()
    result = ClaudePilot(mode="pilot", journal=False).execute(
        scenario, "SLSQP", max_iter=10
    )
    assert result.stop_reason == "no backend"
    assert len(scenario.formulation.optimization_problem.database) == 10


def test_a_switch_of_algorithm_starts_a_new_segment_from_the_best_point():
    scenario = rosenbrock()
    problem = scenario.formulation.optimization_problem
    result = pilot([switch()]).execute(scenario, "SLSQP", max_iter=20)

    first, second = result.segments
    assert (first.algo_name, first.ended) == ("SLSQP", "decision")
    assert second.algo_name == "NLOPT_COBYLA"
    assert second.settings["max_iter"] == 20 - second.first_evaluation
    assert second.first_evaluation == first.last_evaluation + 1
    assert second.reason.startswith("switch_algorithm: A derivative-free method")
    assert len(problem.database) <= 20
    assert result.stop_reason in {"completed", "budget spent"}
    assert [decision.action.kind for decision in result.decisions] == [
        "switch_algorithm"
    ]
    # The design space ends at the best evaluation.
    objective = problem.database.get_function_history("f")
    best_x = problem.database.get_x_vect_history()[result.best_evaluation]
    assert objective[result.best_evaluation] == pytest.approx(objective.min())
    assert np.allclose(problem.design_space.get_current_value(), best_x)


def test_narrowed_bounds_apply_to_the_next_segment_then_are_given_back():
    narrow = FakeBackend.decision(
        {
            "diagnosis": "The optimum is near x = 1.",
            "action": {
                "kind": "change_design_space",
                "variables": [{"name": "x", "lower": 0.0, "upper": 1.5}],
            },
        }
    )
    scenario = rosenbrock()
    problem = scenario.formulation.optimization_problem
    result = pilot([narrow]).execute(scenario, "SLSQP", max_iter=20)

    second = result.segments[1]
    xs = problem.database.get_x_vect_history()[second.first_evaluation :]
    assert len(xs) > 0
    assert all(0.0 <= x[0] <= 1.5 for x in xs)
    assert problem.design_space.get_lower_bound("x") == -2.0
    assert problem.design_space.get_upper_bound("x") == 2.0


def test_stop():
    stop = FakeBackend.decision(
        {"diagnosis": "Converged.", "action": {"kind": "stop", "reason": "converged"}}
    )
    scenario = rosenbrock()
    result = pilot([stop]).execute(scenario, "SLSQP", max_iter=20)
    assert result.stop_reason == "stopped by Claude"
    assert len(result.segments) == 1
    assert len(scenario.formulation.optimization_problem.database) < 20


def test_the_observer_applies_nothing():
    backend_script = [switch()]  # Refused: an observer may only diagnose.
    result = pilot(backend_script, mode="observer").execute(
        rosenbrock(), "SLSQP", max_iter=12
    )
    assert len(result.segments) == 1
    assert result.decisions == []
    assert "The run is fine." in result.diagnoses


def test_the_advisor_mode_observes_in_a_script():
    advisor = pilot([switch()], mode="advisor")
    result = advisor.execute(rosenbrock(), "SLSQP", max_iter=12)
    assert advisor.journal.records[0]["mode"] == "observer"
    assert result.decisions == []


def test_a_refused_decision_is_not_applied():
    widen = FakeBackend.decision(
        {
            "diagnosis": "Look further.",
            "action": {
                "kind": "change_design_space",
                "variables": [{"name": "x", "upper": 5.0}],
            },
        }
    )
    result = pilot([widen, widen]).execute(rosenbrock(), "SLSQP", max_iter=12)
    assert result.decisions == []
    assert len(result.segments) == 1


def test_three_failures_turn_the_pilot_off():
    errors = [BackendError("down")] * 3
    scenario = rosenbrock()
    result = pilot(errors, then=switch()).execute(scenario, "SLSQP", max_iter=15)
    assert result.disabled.startswith("3 calls failed in a row")
    assert result.decisions == []
    assert len(scenario.formulation.optimization_problem.database) > 9


def test_an_authentication_error_turns_the_pilot_off_at_once():
    result = pilot([AuthenticationError("no login")]).execute(
        rosenbrock(), "SLSQP", max_iter=10
    )
    assert result.disabled == "authentication failed: no login"


def test_the_start_review_can_change_the_first_segment():
    triggers = TriggerSettings(period=None, events=False, end=False)
    result = pilot([switch()], triggers=triggers).execute(
        rosenbrock(), "SLSQP", max_iter=10
    )
    assert [segment.algo_name for segment in result.segments] == ["NLOPT_COBYLA"]


def test_the_end_call_can_ask_for_another_segment():
    triggers = TriggerSettings(period=None, events=False, start=False)
    result = pilot([switch()], triggers=triggers).execute(
        rosenbrock(), "SLSQP", max_iter=100, ftol_rel=1e-2
    )
    assert [segment.algo_name for segment in result.segments] == [
        "SLSQP",
        "NLOPT_COBYLA",
    ]
    assert result.segments[0].ended == "completed"


def test_a_slow_answer_does_not_block_the_optimizer():
    slow = Delayed(0.2, switch())
    triggers = TriggerSettings(
        period=2, min_interval=0, check_every=1, start=False, end=False
    )
    slow_pilot = pilot([slow], triggers=triggers, threaded=True)
    start = time.perf_counter()
    result = slow_pilot.execute(rosenbrock(), "SLSQP", max_iter=100, ftol_rel=1e-2)
    assert time.perf_counter() - start < 0.8
    records = slow_pilot.journal.records
    answer = next(record for record in records if record["kind"] == "answer")
    # The optimizer went on while Claude was thinking.
    assert result.segments[0].last_evaluation > answer["evaluation"]
    assert result.segments[1].algo_name == "NLOPT_COBYLA"


def test_journal(tmp_path):
    path = tmp_path / "run" / "journal.jsonl"
    triggers = TriggerSettings(
        period=3, events=False, start=False, min_interval=0, check_every=1
    )
    pilot([switch()], triggers=triggers, journal=path).execute(
        rosenbrock(), "SLSQP", max_iter=20
    )
    kinds = [record["kind"] for record in read_journal(path)]
    assert kinds[0] == "status"
    assert {"call", "answer", "decision", "segment"} <= set(kinds)
    assert kinds[-1] == "status"
    records = list(read_journal(path))
    assert records[-1]["state"] == "finished"
    call = next(record for record in records if record["kind"] == "call")
    assert '"trigger": "periodic"' in call["context"]
    assert call["model"] == "claude-opus-5-5"


class RunInterruptedError(Exception):
    pass


def test_journal_of_an_interrupted_run(tmp_path):
    path = tmp_path / "journal.jsonl"
    scenario = rosenbrock()
    database = scenario.formulation.optimization_problem.database

    def interrupt(x):
        if len(database) > 4:
            raise RunInterruptedError

    database.add_new_iter_listener(interrupt)
    with pytest.raises(RunInterruptedError):
        pilot([], journal=path).execute(scenario, "SLSQP", max_iter=20)
    records = list(read_journal(path))
    assert records[-1] == records[-1] | {"kind": "status", "state": "interrupted"}
