"""Leaving the violated domain: a working set of the most violated constraints."""

import numpy as np
import pytest

from gemseo_lso import Optimizer
from gemseo_lso import Settings
from gemseo_lso.benchmarks.synthetic import LocalConstraints
from gemseo_lso.core import optimizer as core
from gemseo_lso.core.settings import SettingsError

GCMMA = {"method": "gcmma", "dual_solver": "lbfgsb"}
NEVER = {"violated_share": 1.0}
SIZE = 120


@pytest.fixture(autouse=True)
def few_rows(monkeypatch):
    """A working set of at least 20 rows, not 100: the problems here are small."""
    monkeypatch.setattr(core, "MIN_VIOLATED_ROWS", 20)


def saturated():
    """The synthetic problem, where a third of the constraints are active at the
    solution and violated at the start: a start outside the feasible domain."""
    return LocalConstraints(SIZE, active_share=0.6, seed=1)


def violated_share(problem):
    constraints = problem.values(problem.x0)[1]
    return float(np.mean(constraints > 1e-5))


def test_the_start_of_these_tests_violates_many_constraints():
    assert violated_share(saturated()) > 0.25
    assert violated_share(LocalConstraints(SIZE, active_share=0.05, seed=1)) < 0.25


def test_outside_the_domain_the_working_set_holds_the_most_violated_only():
    inside = Optimizer(saturated(), Settings(**GCMMA, **NEVER)).step()
    outside = Optimizer(saturated(), Settings(**GCMMA)).step()
    assert outside.outside
    assert not inside.outside
    # A tenth of the constraints, at least 20 here: not all the violated ones.
    assert outside.working_set < 0.7 * inside.working_set


def test_the_run_leaves_the_domain_and_finds_the_optimum():
    problem = saturated()
    reports = list(Optimizer(problem, Settings(**GCMMA, max_iter=200)))
    assert reports[0].outside
    assert not reports[-1].outside
    assert reports[-1].status == "converged"
    assert reports[-1].max_constraint <= 1e-5
    assert reports[-1].objective == pytest.approx(problem.optimum, rel=1e-3)


def test_inside_the_domain_nothing_changes():
    on = Optimizer(LocalConstraints(60, seed=1), Settings(**GCMMA)).run()
    off = Optimizer(LocalConstraints(60, seed=1), Settings(**GCMMA, **NEVER)).run()
    assert on.iterations == off.iterations
    assert on.x == pytest.approx(off.x, abs=1e-12)


def test_outside_a_constraint_is_repaired_only_when_a_step_makes_it_worse():
    optimizer = Optimizer(saturated(), Settings(**GCMMA))
    before = optimizer.state.constraints.copy()
    tolerance = optimizer.settings.ineq_tolerance
    violated = np.flatnonzero(before > 10 * tolerance)
    worse, same, better = violated[:3], violated[3:6], violated[6:9]
    new = before.copy()
    new[worse] += 1.0
    new[better] -= 0.5 * before[better]
    optimizer._outside = True
    assert set(np.flatnonzero(optimizer._to_repair(new))) == set(worse)
    assert not optimizer._to_repair(new)[same].any()
    # Inside the domain, every violated constraint is.
    optimizer._outside = False
    assert optimizer._to_repair(new)[same].all()


def test_the_hysteresis_keeps_the_run_outside_until_half_the_share():
    optimizer = Optimizer(saturated(), Settings(**GCMMA))
    constraints = optimizer.state.constraints
    low = np.full(constraints.size, -1.0)
    for share, expected in ((0.2, False), (0.3, True), (0.2, True), (0.1, False)):
        optimizer.state.constraints = low.copy()
        optimizer.state.constraints[: int(share * low.size)] = 1.0
        optimizer._update_outside()
        assert optimizer._outside is expected, share


@pytest.mark.parametrize(
    "changes",
    [
        {"violated_share": -0.1},
        {"violated_working_set": 0.0},
        {"violated_working_set": 1.5},
    ],
)
def test_the_settings_are_checked(changes):
    with pytest.raises(SettingsError):
        Settings(**changes)
