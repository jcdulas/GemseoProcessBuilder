import io
from dataclasses import replace

import numpy as np
import pytest
from lso_problems import cantilever
from lso_problems import hs43

from gemseo_lso.core import DenseProblem
from gemseo_lso.core import Optimizer
from gemseo_lso.core import ProblemError
from gemseo_lso.core import Settings
from gemseo_lso.core import SettingsError
from gemseo_lso.core import State


@pytest.mark.parametrize("method", ["mma", "gcmma"])
def test_a_saved_state_resumes_exactly(method):
    settings = Settings(method=method, dual_solver="lbfgsb")
    uninterrupted = Optimizer(hs43().problem, settings)
    whole = uninterrupted.run()

    first = Optimizer(hs43().problem, settings)
    for _ in range(5):
        first.step()
    saved = io.BytesIO()  # An HDF5 file in memory: no disk, no antivirus scan.
    first.state.save(saved)
    resumed = Optimizer(hs43().problem, settings, State.load(saved))
    result = resumed.run()

    assert np.array_equal(result.x, whole.x)
    assert (result.iterations, result.evaluations, result.row_evaluations) == (
        whole.iterations,
        whole.evaluations,
        whole.row_evaluations,
    )
    assert resumed.state.history == uninterrupted.state.history


def test_settings_change_between_two_steps():
    optimizer = Optimizer(cantilever().problem)
    optimizer.step()
    optimizer.settings = replace(optimizer.settings, move_limit=0.01)
    report = optimizer.step()
    assert report.step <= 0.01 + 1e-12


def test_stop_ends_the_run_cleanly():
    optimizer = Optimizer(cantilever().problem)
    reports = []
    for report in optimizer:
        reports.append(report)
        if report.iteration == 2:
            optimizer.stop("enough")
    assert [r.iteration for r in reports] == [1, 2]
    result = optimizer.result
    assert result.status == "stopped"
    assert result.message.startswith("enough")
    with pytest.raises(RuntimeError, match="ended"):
        optimizer.step()


def test_reports():
    known = cantilever()
    optimizer = Optimizer(known.problem, Settings(method="gcmma"))
    reports = list(optimizer)
    assert reports[-1].status == "converged"
    first = reports[0]
    assert (first.working_set, first.rows_computed, first.rows_reused) == (1, 1, 0)
    assert first.asymptote_spread[0] > 0
    assert first.model_time >= 0 and first.optimizer_time > 0
    assert sum(r.rows_computed for r in reports) == known.problem.rows
    assert optimizer.result.evaluations == known.problem.evaluations


def test_max_iter():
    result = Optimizer(cantilever().problem, Settings(max_iter=3)).run()
    assert (result.status, result.iterations) == ("max_iter", 3)


@pytest.mark.parametrize("method", ["mma", "gcmma"])
@pytest.mark.parametrize(("objective", "constraint"), [(1e-4, 1e4), (1e4, 1e-4)])
def test_the_units_of_the_problem_change_nothing(method, objective, constraint):
    c = np.array([61.0, 37.0, 19.0, 7.0, 1.0])
    scaled = DenseProblem(
        x0=np.full(5, 5.0),
        lower=np.full(5, 1.0),
        upper=np.full(5, 10.0),
        objective=lambda x: float(objective * 0.0624 * x.sum()),
        objective_gradient=lambda x: np.full(5, objective * 0.0624),
        constraints=lambda x: constraint * np.array([np.sum(c / x**3) - 1.0]),
        constraint_jacobian=lambda x: constraint * (-3 * c / x**4)[None, :],
    )
    tolerance = Settings().ineq_tolerance
    reference = Optimizer(cantilever().problem, Settings(method=method)).run()
    result = Optimizer(
        scaled, Settings(method=method, ineq_tolerance=constraint * tolerance)
    ).run()
    assert result.status == reference.status == "converged"
    assert result.iterations == reference.iterations
    assert np.allclose(result.x, reference.x, atol=1e-3)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"move_limit": 0}, "move_limit must be positive"),
        ({"move_limit": 2}, "fraction of the ranges"),
        ({"asymptote_decrease": 1.5}, r"asymptote_decrease must be in \]0, 1\]"),
        ({"asymptote_increase": 0.5}, "at least 1"),
        ({"ftol_rel": -1}, "zero or positive"),
        ({"method": "sqp"}, "mma or gcmma"),
    ],
)
def test_settings_out_of_range(changes, message):
    with pytest.raises(SettingsError, match=message):
        Settings(**changes)


def one_variable(lower, upper, equality=False):
    problem = DenseProblem(
        x0=np.array([0.5]),
        lower=np.array([lower]),
        upper=np.array([upper]),
        objective=lambda x: float(x[0]),
        objective_gradient=lambda x: np.ones(1),
        constraints=lambda x: np.zeros(0),
        constraint_jacobian=lambda x: np.zeros((0, 1)),
    )
    if equality:
        problem.values = lambda x: (float(x[0]), np.zeros(0), np.ones(1))
    return problem


def test_problems_the_optimizer_refuses():
    with pytest.raises(ProblemError, match="finite bounds"):
        Optimizer(one_variable(0.0, np.inf))
    with pytest.raises(ProblemError, match="above its lower bound"):
        Optimizer(one_variable(1.0, 1.0))
    with pytest.raises(ProblemError, match="at most 0 are supported"):
        Optimizer(one_variable(0.0, 1.0, equality=True), Settings(max_equality=0))


def test_without_constraints():
    result = Optimizer(one_variable(0.0, 1.0)).run()
    assert (result.status, result.x[0]) == ("converged", pytest.approx(0.0))


def test_a_move_keeps_the_state_of_the_optimizer():
    problem = cantilever().problem
    optimizer = Optimizer(problem, Settings(method="mma"))
    for _ in range(3):
        optimizer.step()
    state = optimizer.state
    x = state.x.copy()
    spreads = (x - state.lower_asymptote, state.upper_asymptote - x)
    evaluations = state.evaluations
    moved = x + 0.2
    optimizer.move(moved)
    assert state.x == pytest.approx(moved)
    assert state.evaluations == evaluations + 1
    assert state.objective == pytest.approx(problem.values(moved)[0])
    assert (moved - state.lower_asymptote) == pytest.approx(spreads[0])
    assert (state.upper_asymptote - moved) == pytest.approx(spreads[1])
    assert optimizer.run().status == "converged"
