"""The solver on problems of the literature, and what they showed (plan 74)."""

import warnings
from dataclasses import replace

import numpy as np
import pytest
from scipy.linalg import solve
from test_lso_subproblem import approximation

from gemseo_lso.benchmarks.literature import classics
from gemseo_lso.benchmarks.literature.trusses import seventy_two_bar
from gemseo_lso.benchmarks.literature.trusses import ten_bar
from gemseo_lso.benchmarks.literature.trusses import twenty_five_bar
from gemseo_lso.core import Optimizer
from gemseo_lso.core import Settings
from gemseo_lso.core import dual
from gemseo_lso.core.dual import SubproblemSolution
from gemseo_lso.core.dual import checked
from gemseo_lso.core.dual import solve_dual
from gemseo_lso.core.dual import solve_interior_point
from gemseo_lso.core.dual import solve_scaled
from gemseo_lso.core.settings import SettingsError

TRUSSES = [ten_bar, twenty_five_bar, seventy_two_bar]


@pytest.mark.parametrize("make", TRUSSES)
def test_the_published_designs_are_reproduced(make):
    # The geometry is a figure in the papers: rebuilt, then checked against the
    # weight of the published optimal areas, and the constraints they make active.
    truss = make()
    areas = truss.published
    assert truss.weight(areas) == pytest.approx(truss.known[0], abs=0.02)
    values, _ = truss.constraints(areas)
    assert values.max() <= 1e-5  # Feasible to the digits of the papers,
    assert values.max() > -1e-5  # and on a limit.
    assert np.count_nonzero(values > -1e-3) >= 2


@pytest.mark.parametrize("make", TRUSSES)
def test_the_jacobian_of_a_truss(make):
    truss = make()
    areas = truss.published
    values, rows = truss.constraints(areas)
    for k in (0, truss.size // 2, truss.size - 1):
        shifted = areas.copy()
        shifted[k] += 1e-7
        slope = (truss.constraints(shifted)[0] - values) / 1e-7
        assert slope == pytest.approx(rows[:, k], rel=1e-4, abs=1e-5)


@pytest.mark.parametrize("make", TRUSSES)
def test_the_solver_finds_the_published_optimum(make):
    truss = make()
    result = Optimizer(truss.problem(0.5), Settings(method="mma", max_iter=100)).run()
    areas = truss.areas(result.x)
    assert result.status == "converged"
    assert truss.weight(areas) == pytest.approx(truss.known[0], rel=1e-4)
    assert truss.worst(areas) <= 1e-5
    assert result.iterations <= 30


def test_the_ten_bar_truss_has_a_second_local_optimum():
    # Schmit and Miura's 5076.85 lb: GCMMA lands on it from most starts, a real
    # local optimum (SLSQP, started there, stays), not a false convergence.
    truss = ten_bar()
    problem = truss.problem(0.5)
    result = Optimizer(problem, Settings(method="gcmma", max_iter=100)).run()
    weight = truss.weight(truss.areas(result.x))
    assert min(abs(weight / 5060.85 - 1), abs(weight / 5076.85 - 1)) < 1e-3


@pytest.mark.parametrize(
    ("make", "tolerance"), [(classics.hs71, 1e-6), (classics.hs100, 1e-5)]
)
def test_the_hock_schittkowski_problems(make, tolerance):
    problem, x_star, f_star = make()
    settings = Settings(
        method="gcmma", dual_solver="lbfgsb", ineq_tolerance=1e-6, eq_tolerance=1e-6
    )
    result = Optimizer(problem, settings).run()
    objective, values, equalities = problem.values(result.x)
    assert result.status == "converged"
    assert objective == pytest.approx(f_star, rel=tolerance)
    assert values.max() <= 1e-5
    assert np.abs(equalities).max(initial=0.0) <= 1e-5
    assert result.x == pytest.approx(x_star, abs=1e-2)


@pytest.mark.parametrize("method", ["mma", "gcmma"])
def test_the_beam_of_svanberg(method):
    problem, y_star, f_star = classics.beam(5)
    result = Optimizer(problem, Settings(method=method, max_iter=200)).run()
    assert result.status == "converged"
    assert problem.values(result.x)[0] == pytest.approx(f_star, rel=1e-6)
    assert result.x == pytest.approx(y_star, rel=2e-3)


def test_a_beam_of_a_thousand_segments():
    # The interior point does not finish it (see the solver choice): L-BFGS-B
    # solves its single constraint, whatever the number of variables.
    problem, _, f_star = classics.beam(2000)
    result = Optimizer(problem, Settings(method="gcmma", max_iter=100)).run()
    assert result.status == "converged"
    assert problem.values(result.x)[0] == pytest.approx(f_star, rel=1e-6)
    assert problem.values(result.x)[1].max() <= 1e-5


def test_a_dual_that_lbfgsb_left_unsolved_is_started_again(monkeypatch):
    # On the beam of 10^4 segments, L-BFGS-B ended with a failed line search in
    # 6 of 15 subproblems, its projected gradient far above the tolerance.
    a = approximation(n=30, m=5)
    real = dual.minimize
    calls = []

    def failing_first(*args, **kwargs):
        result = real(*args, **kwargs)
        calls.append(kwargs["options"]["gtol"])
        if len(calls) == 1:
            result.success = False
            result.jac = np.full_like(result.jac, 1.0)  # Far from stationary.
        return result

    monkeypatch.setattr(dual, "minimize", failing_first)
    solution = solve_dual(a, 1000.0, 1.0, np.zeros(5), 1e-6)
    assert len(calls) == 2
    assert solve_dual(a, 1000.0, 1.0, np.zeros(5), 1e-6).multipliers == pytest.approx(
        solution.multipliers
    )


def test_an_interior_point_that_did_not_converge_is_solved_again():
    a = approximation(n=30, m=5)
    exact = solve_interior_point(a, 1000.0, 1.0)
    assert exact.converged
    failed = replace(exact, multipliers=exact.multipliers * 0.1, converged=False)
    again = checked(a, failed, 1000.0, 1.0, 1e-7)
    assert again.multipliers == pytest.approx(exact.multipliers, rel=1e-3, abs=1e-6)
    same = checked(a, exact, 1000.0, 1.0, 1e-7)
    assert same is exact  # A converged solution is not solved again.


def test_the_interior_point_reports_when_it_did_not_converge():
    a = approximation(n=30, m=5)
    solution = SubproblemSolution(a.x, np.zeros(5), np.zeros(5))
    assert solution.converged  # By default.
    assert not replace(solution, converged=False).converged


def test_an_ill_conditioned_reduced_system_is_solved_accurately():
    # The diagonal of the barrier terms spans 30 orders of magnitude at the end
    # of the interior point: LAPACK warned of an inaccurate result on the trusses.
    rng = np.random.default_rng(1)
    size = 12
    scales = np.logspace(-20, 10, size)
    base = np.eye(size) + 0.1 * (lambda m: m @ m.T / size)(
        rng.standard_normal((size, size))
    )
    matrix = np.sqrt(scales)[:, None] * base * np.sqrt(scales)[None, :]
    unit = rng.standard_normal(size)
    right = np.sqrt(scales) * (
        base @ unit
    )  # Without the cancellation of matrix @ truth.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        solution = solve_scaled(matrix, right)
    assert not caught
    assert solution * np.sqrt(scales) == pytest.approx(unit, rel=1e-6)
    with warnings.catch_warnings(record=True) as plain:
        warnings.simplefilter("always")
        solve(matrix, right, assume_a="pos")
    assert plain  # The unscaled system does warn.


def test_the_solver_of_the_dual_depends_on_the_size_of_the_problem():
    # Few constraints and many variables: L-BFGS-B; else the interior point.
    problem, _, _ = classics.beam(600)
    optimizer = Optimizer(problem, Settings(method="mma", max_iter=1))
    seen = []
    original = dual.solve_interior_point

    def spy(*args, **kwargs):
        seen.append("interior point")
        return original(*args, **kwargs)

    from gemseo_lso.core import optimizer as core

    core.solve_interior_point = spy
    try:
        optimizer.step()
        small, _, _ = classics.beam(50)
        Optimizer(small, Settings(method="mma", max_iter=1)).step()
    finally:
        core.solve_interior_point = original
    assert seen == ["interior point"]  # The beam of 50 only.


def test_the_descent_goes_through_the_constraints_then_comes_back():
    # From the neutral start, the design goes down with soft constraints, ends
    # outside them, and the restoration brings it back before the normal
    # iterations: the 10-bar truss then reaches its global optimum with GCMMA,
    # which lands in the local one (5076.85 lb) without it.
    truss = ten_bar()
    optimizer = Optimizer(
        truss.problem(0.5),
        Settings(method="gcmma", max_iter=100, descent_iterations=5),
    )
    reports = list(optimizer)
    descent = [report for report in reports if report.descent]
    assert [report.descent for report in descent] == [1, 2, 3, 4, 5]
    assert max(report.max_constraint for report in descent) > 0  # Went through.
    assert reports[-1].max_constraint <= 1e-5  # And came back.
    areas = truss.areas(optimizer.result.x)
    assert truss.weight(areas) == pytest.approx(truss.known[0], rel=1e-4)


def test_the_descent_ends_when_the_objective_settles():
    truss = twenty_five_bar()
    optimizer = Optimizer(
        truss.problem(0.5), Settings(method="mma", max_iter=100, descent_iterations=50)
    )
    reports = list(optimizer)
    assert 0 < max(report.descent for report in reports) < 10
    assert optimizer.result.status == "converged"


def test_the_descent_is_off_by_default():
    assert Settings().descent_iterations == 0
    with pytest.raises(SettingsError):
        Settings(descent_iterations=-1)
