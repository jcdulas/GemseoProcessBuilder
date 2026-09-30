import numpy as np
import pytest
from pilot_samples import problem
from pilot_samples import rosenbrock_doe
from pilot_samples import small_bilevel

from gemseo_claude_pilot import ClaudePilot
from gemseo_claude_pilot import Decision
from gemseo_claude_pilot import Limits
from gemseo_claude_pilot import RejectedDecisionError
from gemseo_claude_pilot import check
from gemseo_claude_pilot.backends import FakeBackend
from gemseo_claude_pilot.privacy import Anonymizer
from gemseo_claude_pilot.snapshots import SubScenario
from gemseo_claude_pilot.triggers import TriggerSettings

FINE = FakeBackend.decision({"diagnosis": "Enough."})
AT_SEGMENT_ENDS = TriggerSettings(period=None, events=False, start=False)


def pilot(script, triggers=AT_SEGMENT_ENDS, **options):
    return ClaudePilot(
        mode="pilot",
        backend=FakeBackend(script, then=FINE),
        triggers=triggers,
        journal=False,
        threaded=False,
        report=False,
        **options,
    )


def decision(action):
    return FakeBackend.decision({"diagnosis": "d", "action": action})


def test_a_doe_is_sampled_in_segments():
    scenario = rosenbrock_doe()
    problem_ = scenario.formulation.optimization_problem
    more = decision(
        {
            "kind": "add_samples",
            "algo_name": "LHS",
            "n_samples": 4,
            "region": [{"name": "x", "lower": 0.5, "upper": 1.5}],
        }
    )
    result = pilot([more]).execute(scenario, "LHS", n_samples=12)

    first, second, rest = result.segments
    assert first.settings["n_samples"] == 6  # Claude places the other half.
    assert (second.algo_name, second.settings["n_samples"]) == ("LHS", 4)
    assert rest.reason == "the samples left, drawn as the user asked"
    assert rest.settings["n_samples"] == 2
    points = problem_.database.get_x_vect_history()
    assert len(points) == 12
    assert all(0.5 <= x[0] <= 1.5 for x in points[6:10])
    assert len({tuple(x) for x in points}) == 12  # No sample drawn twice.
    # The region held for its segment only.
    assert problem_.design_space.get_lower_bound("x")[0] == -2.0


def test_a_doe_without_seed_keeps_its_samples():
    scenario = rosenbrock_doe()
    result = pilot([]).execute(scenario, "DiagonalDOE", n_samples=9)
    assert [segment.settings["n_samples"] for segment in result.segments] == [9]
    assert len(scenario.formulation.optimization_problem.database) == 9


def test_claude_stops_a_doe():
    scenario = rosenbrock_doe()
    stop = decision({"kind": "stop", "reason": "converged"})
    result = pilot([stop]).execute(scenario, "LHS", n_samples=12)
    assert result.stop_reason == "stopped by Claude"
    assert len(scenario.formulation.optimization_problem.database) == 6


def test_a_doe_without_n_samples_runs_as_is():
    scenario = rosenbrock_doe()
    samples = np.array([[0.0, 0.0], [1.0, 1.0]])
    result = pilot([]).execute(scenario, "CustomDOE", samples=samples)
    assert result.disabled == "a DOE needs n_samples to be piloted"
    assert len(scenario.formulation.optimization_problem.database) == 2


def test_claude_retunes_a_sub_optimization_of_a_bilevel_study():
    scenario = small_bilevel()
    retune = decision(
        {
            "kind": "change_sub_scenario",
            "scenario": "LeftOptimizer",
            "settings": {"max_iter": 3},
        }
    )
    every_two = TriggerSettings(
        period=2, min_interval=0, check_every=1, start=False, end=False
    )
    bilevel = pilot([retune], triggers=every_two)
    result = bilevel.execute(scenario, "NLOPT_COBYLA", max_iter=6)

    assert len(result.segments) == 1  # Applied without ending the segment.
    assert [made.action.kind for made in result.decisions] == ["change_sub_scenario"]
    left, right = scenario.formulation.get_sub_scenarios()
    assert left._settings.algo_settings["max_iter"] == 3
    assert right._settings.algo_settings["max_iter"] == 10
    call = next(r for r in bilevel.journal.records if r["kind"] == "call")
    assert '"name": "LeftOptimizer"' in call["context"]
    assert '"gradients": "none"' in call["context"]
    assert '"name": "Left"' in call["context"]  # A component of a sub-optimization.


SUBS = (
    SubScenario("LeftOptimizer", "SLSQP", {"max_iter": 10}, ("x1",), "y1"),
    SubScenario("RightOptimizer", "SLSQP", {"max_iter": 10}, ("x2",), "y2"),
)


def sub_decision(**action):
    return Decision.model_validate(
        {"diagnosis": "d", "action": {"kind": "change_sub_scenario", **action}}
    )


@pytest.mark.parametrize(
    ("action", "reason"),
    [
        (
            {"scenario": "Middle", "settings": {"max_iter": 3}},
            "no sub-optimization named Middle",
        ),
        ({"scenario": "LeftOptimizer"}, "changes nothing"),
        (
            {"scenario": "LeftOptimizer", "algo_name": "Magic"},
            "no optimization algorithm named Magic",
        ),
        ({"scenario": "LeftOptimizer", "settings": {"no_such": 1}}, "no_such"),
    ],
)
def test_refused_changes_of_a_sub_optimization(action, reason):
    snapshot = problem(sub_scenarios=SUBS)
    with pytest.raises(RejectedDecisionError, match=reason):
        check(sub_decision(**action), snapshot, Limits.of(snapshot), 5)


def test_accepted_change_of_a_sub_optimization():
    snapshot = problem(sub_scenarios=SUBS)
    made = sub_decision(scenario="RightOptimizer", settings={"max_iter": 3})
    assert check(made, snapshot, Limits.of(snapshot), 5).decision == made


def test_anonymized_sub_optimizations():
    snapshot = problem(sub_scenarios=SUBS)
    anonymizer = Anonymizer(snapshot)
    hidden = anonymizer.problem(snapshot)
    assert [sub.name for sub in hidden.sub_scenarios] == ["s1", "s2"]
    assert "x1" not in str(hidden.sub_scenarios)
    real = anonymizer.decision(sub_decision(scenario="s1", settings={"max_iter": 3}))
    assert real.action.scenario == "LeftOptimizer"


def test_a_surrogate_is_described_with_its_quality():
    from gemseo import create_surrogate
    from gemseo.datasets.io_dataset import IODataset

    from gemseo_claude_pilot.snapshots import surrogate_description

    dataset = IODataset()
    x = np.linspace(0, 1, 8).reshape(-1, 1)
    dataset.add_input_variable("x", x)
    dataset.add_output_variable("y", 2 * x + 1)
    surrogate = create_surrogate("LinearRegressor", dataset)
    assert surrogate_description(surrogate) == (
        "Surrogate model (LinearRegressor) trained on 8 samples; "
        "R2 on its training data: 1.000"
    )
