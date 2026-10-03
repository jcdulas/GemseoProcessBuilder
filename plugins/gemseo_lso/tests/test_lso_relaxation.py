"""Relaxing constraints, then bringing them back (spec § 3.10)."""

import numpy as np
import pytest

from gemseo_lso import DenseProblem
from gemseo_lso import Optimizer
from gemseo_lso import Settings
from gemseo_lso.core.relaxation import relax_state
from gemseo_lso.core.relaxation import tighten_state
from gemseo_lso.core.relaxation import true_constraints
from gemseo_lso.core.state import State

SETTINGS = {"method": "gcmma", "dual_solver": "lbfgsb", "move_limit": 0.2}


def bridge(x0=0.9):
    """Minimize x where the points within 0.1 of 0.5 are forbidden.

    The objective falls toward x = 0, the best design; starting above the gap,
    the constraint holds the run at 0.6, the best design on that side. Relaxed
    by more than 0.01, the gap is open.
    """
    return DenseProblem(
        x0=np.array([x0]),
        lower=np.zeros(1),
        upper=np.ones(1),
        objective=lambda x: float(x[0]),
        objective_gradient=lambda x: np.ones(1),
        constraints=lambda x: np.array([0.01 - (x[0] - 0.5) ** 2]),
        constraint_jacobian=lambda x: np.array([[-2 * (x[0] - 0.5)]]),
    )


def floor(level=0.6, x0=0.9):
    """Minimize x subject to x >= level."""
    return DenseProblem(
        x0=np.array([x0]),
        lower=np.zeros(1),
        upper=np.ones(1),
        objective=lambda x: float(x[0]),
        objective_gradient=lambda x: np.ones(1),
        constraints=lambda x: np.array([level - x[0]]),
        constraint_jacobian=lambda x: np.array([[-1.0]]),
    )


def state_with(constraints):
    constraints = np.asarray(constraints, dtype=float)
    return State(
        x=np.zeros(1),
        objective=0.0,
        constraints=constraints,
        multipliers=np.zeros(constraints.size),
        constraints_previous=constraints.copy(),
    )


# The state.


def test_a_relaxed_constraint_has_an_effective_value_and_a_true_one():
    state = state_with([0.3, -0.2, 0.1])
    relax_state(state, np.array([0, 2]), 0.25)
    assert state.constraints == pytest.approx([0.05, -0.2, -0.15])
    assert state.constraints_previous == pytest.approx([0.05, -0.2, -0.15])
    assert true_constraints(state) == pytest.approx([0.3, -0.2, 0.1])
    assert state.relaxation == pytest.approx([0.25, 0.0, 0.25])


def test_tightening_brings_the_constraints_back_to_the_original_ones():
    state = state_with([0.3, -0.2, 0.1])
    relax_state(state, np.array([0, 2]), 0.25)
    tighten_state(state, 0.5)
    assert state.relaxation == pytest.approx([0.125, 0.0, 0.125])
    assert state.constraints == pytest.approx([0.175, -0.2, -0.025])
    tighten_state(state, 0.0)
    assert state.relaxation is None
    assert state.constraints == pytest.approx([0.3, -0.2, 0.1])


def test_small_offsets_vanish_with_the_tolerance():
    state = state_with([0.3, -0.2])
    relax_state(state, np.array([0]), 1e-4)
    tighten_state(state, 0.5, tolerance=1e-4)
    assert state.relaxation is None


@pytest.mark.parametrize("amount", [-0.1])
def test_a_negative_amount_is_refused(amount):
    with pytest.raises(ValueError, match="positive"):
        relax_state(state_with([0.0]), np.array([0]), amount)


def test_an_unknown_constraint_is_refused():
    with pytest.raises(ValueError, match="numbered 0 to 1"):
        relax_state(state_with([0.0, 0.0]), np.array([2]), 0.1)


def test_a_factor_outside_zero_one_is_refused():
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        tighten_state(state_with([0.0]), 1.5)


def test_the_relaxation_is_saved_with_the_state(tmp_path):
    state = state_with([0.3, -0.2, 0.1])
    relax_state(state, np.array([0]), 0.25)
    state.save(tmp_path / "state.h5")
    loaded = State.load(tmp_path / "state.h5")
    assert loaded.relaxation == pytest.approx([0.25, 0.0, 0.0])
    assert loaded.constraints == pytest.approx(state.constraints)
    plain = state_with([0.3])
    plain.save(tmp_path / "plain.h5")
    assert State.load(tmp_path / "plain.h5").relaxation is None


# The optimizer.


def run_until_stopped(optimizer, limit=60):
    reports = []
    for _ in range(limit):
        if optimizer.finished:
            break
        reports.append(optimizer.step())
    return reports


def test_without_a_relaxation_the_gap_holds_the_run_back():
    result = Optimizer(bridge(), Settings(**SETTINGS, max_iter=60)).run()
    assert result.x[0] == pytest.approx(0.6, abs=1e-2)
    assert result.objective == pytest.approx(0.6, abs=1e-2)


def test_relaxing_the_constraint_opens_the_way_and_tightening_closes_it_again():
    optimizer = Optimizer(bridge(), Settings(**SETTINGS, max_iter=200))
    for _ in range(3):
        optimizer.step()
    optimizer.relax([0], 0.05)
    assert optimizer.relaxation == pytest.approx([0.05])
    relaxed = run_until_stopped(optimizer)
    # The run crossed the gap, to the best design of the problem.
    assert optimizer.state.x[0] == pytest.approx(0.0, abs=1e-2)
    assert relaxed[-1].relaxed == 1
    # The constraint is satisfied there, relaxed or not: the way back is free.
    assert relaxed[-1].max_constraint <= 1e-5
    for factor in (0.5, 0.5, 0.0):
        optimizer.state.status = "running"
        optimizer.tighten(factor)
        run_until_stopped(optimizer, limit=5)
    assert optimizer.relaxation == pytest.approx([0.0])
    result = optimizer.result
    assert result.x[0] == pytest.approx(0.0, abs=1e-2)
    assert result.objective == pytest.approx(0.0, abs=1e-2)
    assert result.max_constraint <= 1e-5


def test_the_reports_and_the_result_stay_those_of_the_original_problem():
    optimizer = Optimizer(floor(), Settings(**SETTINGS, max_iter=200))
    for _ in range(4):
        optimizer.step()  # Feasible, above 0.6.
    best = optimizer.state.best_x.copy()
    assert best[0] > 0.6 - 1e-6
    optimizer.relax([0], 0.3)
    reports = run_until_stopped(optimizer)
    # The relaxed optimum is x = 0.3, violating the original constraint by 0.3.
    assert optimizer.state.x[0] == pytest.approx(0.3, abs=1e-2)
    assert reports[-1].max_constraint == pytest.approx(0.3, abs=1e-2)
    assert reports[-1].violated == 1
    assert reports[-1].relaxed == 1
    # The relaxed run is not "feasible" for the original problem: its result is
    # the best feasible point met, not the relaxed optimum.
    result = optimizer.result
    assert result.x[0] == pytest.approx(best[0])
    assert result.max_constraint <= 1e-5


def test_the_best_feasible_point_ignores_the_points_feasible_only_when_relaxed():
    optimizer = Optimizer(floor(), Settings(**SETTINGS, max_iter=200))
    optimizer.step()
    optimizer.relax([0], 0.5)
    run_until_stopped(optimizer)
    state = optimizer.state
    assert state.x[0] < 0.6  # Past the original limit.
    assert state.best_x[0] >= 0.6 - 1e-5
    assert state.best_objective > state.objective


def test_stopping_when_feasible_lifts_the_relaxation_first():
    optimizer = Optimizer(floor(), Settings(**SETTINGS, max_iter=200))
    optimizer.step()
    optimizer.relax([0], 0.3)
    run_until_stopped(optimizer, limit=2)
    assert optimizer.state.x[0] < 0.6
    assert not optimizer.finished
    optimizer.stop("done", when_feasible=True)
    assert optimizer.relaxation == pytest.approx([0.0])
    run_until_stopped(optimizer)
    assert optimizer.finished
    assert optimizer.state.x[0] >= 0.6 - 1e-4


def test_the_last_iterations_lift_the_relaxation():
    optimizer = Optimizer(
        floor(),
        Settings(**SETTINGS, max_iter=12, restoration_iterations=4, kkt_tolerance=0.0),
    )
    optimizer.step()
    optimizer.relax([0], 0.3)
    reports = run_until_stopped(optimizer)
    assert reports[-1].relaxed == 0
    assert optimizer.result.max_constraint <= 1e-5
    assert any(report.relaxed for report in reports)


def test_a_resumed_run_goes_on_with_the_relaxation(tmp_path):
    optimizer = Optimizer(floor(), Settings(**SETTINGS, max_iter=200))
    optimizer.step()
    optimizer.relax([0], 0.3)
    optimizer.step()
    optimizer.state.save(tmp_path / "state.h5")
    resumed = Optimizer(
        floor(), Settings(**SETTINGS, max_iter=200), State.load(tmp_path / "state.h5")
    )
    assert resumed.relaxation == pytest.approx([0.3])
    run_until_stopped(resumed)
    assert resumed.state.x[0] == pytest.approx(0.3, abs=1e-2)
