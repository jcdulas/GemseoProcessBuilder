import pytest
from pilot_samples import eq
from pilot_samples import ineq
from pilot_samples import problem
from pilot_samples import variable

from gemseo_claude_pilot.algorithms import gemseo_algorithms
from gemseo_claude_pilot.algorithms import incompatibilities
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.guardrails import Limits
from gemseo_claude_pilot.guardrails import RejectedDecisionError
from gemseo_claude_pilot.guardrails import check


def decide(action):
    return Decision.model_validate({"diagnosis": "d", "action": action})


def run_check(action, snapshot=None, used=10, **limits):
    snapshot = snapshot or problem()
    return check(decide(action), snapshot, Limits.of(snapshot, **limits), used)


def rejection(action, snapshot=None, used=10, **limits):
    with pytest.raises(RejectedDecisionError) as error:
        run_check(action, snapshot, used, **limits)
    return str(error.value)


def test_none_and_stop_always_pass():
    assert run_check({"kind": "none"}, used=500).notes == ()
    assert run_check({"kind": "stop", "reason": "budget"}, used=500).notes == ()


def test_action_not_allowed():
    message = rejection(
        {"kind": "stop", "reason": "hopeless"}, allowed_actions=["change_settings"]
    )
    assert "the action stop is not allowed here" in message
    assert message.endswith("Correct it and call submit_decision again.")


def test_action_of_another_driver():
    message = rejection({"kind": "add_samples", "algo_name": "LHS", "n_samples": 5})
    assert "the action add_samples does not apply to an optimization" in message


def test_budget_spent():
    message = rejection(
        {"kind": "change_settings", "settings": {"ftol_rel": 1e-9}}, used=100
    )
    assert "budget is spent" in message


def test_change_settings():
    checked = run_check({"kind": "change_settings", "settings": {"ftol_rel": 1e-9}})
    assert checked.decision.action.settings == {"ftol_rel": 1e-9}


def test_max_iter_clipped_to_the_budget():
    checked = run_check(
        {"kind": "change_settings", "settings": {"max_iter": 500}}, used=70
    )
    assert checked.decision.action.settings == {"max_iter": 30}
    assert checked.notes == (
        "max_iter reduced from 500 to 30, the evaluations left in the budget",
    )


@pytest.mark.parametrize(
    ("settings", "reason"),
    [
        (
            {"ftol_rel": -1},
            "setting ftol_rel: Input should be greater than or equal to 0",
        ),
        ({"unknown": 1}, "setting unknown: Extra inputs are not permitted"),
        ({"use_database": False}, "setting use_database is managed by the pilot"),
    ],
)
def test_wrong_settings(settings, reason):
    assert reason in rejection({"kind": "change_settings", "settings": settings})


def test_switch_algorithm_sets_the_iterations_left():
    checked = run_check(
        {"kind": "switch_algorithm", "algo_name": "NLOPT_COBYLA"}, used=60
    )
    assert checked.decision.action.settings == {"max_iter": 40}


def test_switch_to_an_incompatible_algorithm():
    snapshot = problem(constraints=[eq("h")])
    message = rejection({"kind": "switch_algorithm", "algo_name": "L-BFGS-B"}, snapshot)
    assert "L-BFGS-B does not handle equality constraints" in message


def test_switch_to_an_unknown_algorithm():
    message = rejection({"kind": "switch_algorithm", "algo_name": "Magic"})
    assert "no algorithm named Magic is installed for an optimization" in message


def test_incompatibilities():
    algorithms = gemseo_algorithms("optimization")
    integers = problem(variables=[variable("n", integer=True)], constraints=[ineq("g")])
    assert incompatibilities(algorithms["SLSQP"], integers) == [
        "does not handle integer variables"
    ]
    no_gradient = problem(gradients="none")
    assert incompatibilities(algorithms["SLSQP"], no_gradient) == [
        "needs gradients, which this problem does not provide"
    ]
    assert incompatibilities(algorithms["NLOPT_COBYLA"], no_gradient) == []


def test_narrowed_bounds_accepted():
    checked = run_check(
        {
            "kind": "change_design_space",
            "variables": [{"name": "x", "lower": 2, "upper": 8}],
        }
    )
    assert checked.notes == ()


def test_bounds_widened_beyond_the_user_ones():
    message = rejection(
        {"kind": "change_design_space", "variables": [{"name": "x", "upper": 12}]}
    )
    assert "the bounds of x go beyond the ones the user set (0 to 10)" in message


def test_bounds_widened_back_to_the_user_ones():
    original = problem()
    narrowed = problem(variables=[variable("x", 2, lower=2, upper=4, value=3)])
    limits = Limits.of(original)
    action = {"kind": "change_design_space", "variables": [{"name": "x", "upper": 10}]}
    assert check(decide(action), narrowed, limits, 10).notes == ()


def test_starting_value_moved_into_the_new_bounds():
    checked = run_check(
        {"kind": "change_design_space", "variables": [{"name": "x", "upper": [3, 9]}]}
    )
    assert checked.decision.action.variables[0].value == [3.0, 5.0]
    assert checked.notes == ("the starting value of x moved into its new bounds",)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"name": "y", "upper": 1}, "there is no design variable named y"),
        ({"name": "x", "upper": [1, 2, 3]}, "x upper has 3 values instead of 2"),
        ({"name": "x", "lower": 6, "upper": 4}, "a lower bound of x is above"),
        ({"name": "x", "value": 11}, "the value of x is outside its bounds"),
        (
            {"name": "x", "value": float("nan")},
            "x value has values that are not finite",
        ),
    ],
)
def test_wrong_design_space_changes(change, reason):
    message = rejection({"kind": "change_design_space", "variables": [change]})
    assert reason in message


def test_integer_variables_stay_integer():
    snapshot = problem(variables=[variable("n", integer=True, value=3)])
    message = rejection(
        {"kind": "change_design_space", "variables": [{"name": "n", "upper": 4.5}]},
        snapshot,
    )
    assert "n is an integer variable" in message


def test_add_samples():
    snapshot = problem(driver_kind="doe", algo_name="LHS")
    action = {
        "kind": "add_samples",
        "algo_name": "LHS",
        "n_samples": 50,
        "region": [{"name": "x", "lower": 1, "upper": 2}],
    }
    checked = run_check(action, snapshot, used=80)
    assert checked.decision.action.n_samples == 20
    assert checked.notes == (
        "n_samples reduced from 50 to 20, the evaluations left in the budget",
    )


def test_add_samples_in_a_region_with_a_value():
    snapshot = problem(driver_kind="doe", algo_name="LHS")
    action = {
        "kind": "add_samples",
        "algo_name": "LHS",
        "n_samples": 5,
        "region": [{"name": "x", "value": 1}],
    }
    assert "the region gives a value to x" in rejection(action, snapshot)
