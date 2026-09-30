import numpy as np
import pytest
from lso_problems import hs43

from gemseo_lso import DenseProblem
from gemseo_lso import Optimizer
from gemseo_lso import Settings
from gemseo_lso.benchmarks.synthetic import LocalConstraints
from gemseo_lso.core.rows import RowCache
from gemseo_lso.core.screening import screening_margin
from gemseo_lso.core.screening import working_set

GCMMA = {"method": "gcmma", "dual_solver": "lbfgsb"}
EVERY_ROW = {"screening_margin": 1e9, "screening_margin_min": 1e9}


def synthetic():
    return LocalConstraints(300, active_share=0.05, seed=1)


def test_the_optimum_with_a_fraction_of_the_rows():
    # The solution is known; every row would be 300 per iteration.
    problem = synthetic()
    result = Optimizer(problem, Settings(**GCMMA)).run()
    assert result.status == "converged"
    assert result.x == pytest.approx(problem.solution, abs=1e-3)
    assert problem.rows < 0.3 * 300 * (result.iterations + 1)


def test_without_screening_every_row_is_asked_for():
    problem = LocalConstraints(60, active_share=0.05, seed=1)
    result = Optimizer(problem, Settings(**GCMMA, **EVERY_ROW)).run()
    assert result.x == pytest.approx(problem.solution, abs=1e-3)
    assert problem.rows == 60 * (result.iterations + 1)


class Scaled:
    """A problem whose constraints are multiplied by a factor."""

    def __init__(self, problem, factor):
        self.problem, self.factor = problem, factor

    def __getattr__(self, name):
        return getattr(self.problem, name)

    def values(self, x):
        objective, constraints, equalities = self.problem.values(x)
        return objective, self.factor * constraints, equalities

    def constraint_rows(self, x, indices):
        return self.factor * self.problem.constraint_rows(x, indices)


@pytest.mark.parametrize("factor", [1e-3, 1e3])
def test_the_units_of_the_constraints_change_no_row(factor):
    # With the default dual: L-BFGS-B stops early on a point sensitive to
    # rounding, 1e-9 apart at the first iteration, then drifting.
    reference = synthetic()
    expected = Optimizer(reference, Settings(method="gcmma")).run()
    problem = synthetic()
    tolerance = factor * Settings().ineq_tolerance
    result = Optimizer(
        Scaled(problem, factor), Settings(method="gcmma", ineq_tolerance=tolerance)
    ).run()
    assert result.iterations == expected.iterations
    assert problem.rows == reference.rows
    assert result.x == pytest.approx(expected.x, abs=1e-6)


def test_young_rows_far_from_activity_are_reused():
    problem = synthetic()
    optimizer = Optimizer(problem, Settings(**GCMMA, row_refresh="near_active"))
    reports = list(optimizer)
    assert optimizer.result.x == pytest.approx(problem.solution, abs=1e-3)
    assert sum(report.rows_reused for report in reports) > 0
    assert problem.rows < 0.2 * 300 * optimizer.result.iterations


def test_a_step_violating_a_screened_out_constraint_is_repaired():
    # x1 + x2 <= 0.5 is far at the start (-0.5, beyond the margin of 0.3): out
    # of the working set; the first step, pushed up by the objective, crosses it.
    problem = DenseProblem(
        x0=np.zeros(2),
        lower=np.zeros(2),
        upper=np.ones(2),
        objective=lambda x: float(-x.sum()),
        objective_gradient=lambda x: -np.ones(2),
        constraints=lambda x: np.array([x.sum() - 0.5, x[0] - 5.0]),
        constraint_jacobian=lambda x: np.array([[1.0, 1.0], [1.0, 0.0]]),
    )
    optimizer = Optimizer(problem, Settings(max_iter=1))
    report = optimizer.step()
    assert report.screening_repairs == 1
    assert report.working_set == 1  # The repaired constraint only.
    assert optimizer.state.constraints[0] <= 1e-5


def test_the_largest_constraints_are_kept():
    values = np.array([-0.2, 0.1, -0.05, 0.3, -0.25])
    kept = working_set(values, 0.3, None, np.zeros(5), Settings(max_working_set=2))
    assert kept.tolist() == [1, 3]
    # Without repairs: they add the constraints a step would violate, whatever the cap.
    settings = Settings(max_working_set=10, max_screening_repairs=0, max_iter=1)
    optimizer = Optimizer(synthetic(), settings)
    assert optimizer.step().working_set == 10


def test_the_cap_keeps_every_active_constraint():
    # 0 and 2 are active: kept beyond the cap, which the others fill no more.
    values = np.array([-1e-9, 0.1, -2e-9, 0.3, -0.25])
    multipliers = np.array([1.5, 0.0, 0.8, 0.0, 0.0])
    settings = Settings(max_working_set=3)
    assert working_set(values, 0.3, None, multipliers, settings).tolist() == [0, 2, 3]
    settings = Settings(max_working_set=1)
    assert working_set(values, 0.3, None, multipliers, settings).tolist() == [0, 2]


def test_the_working_set_keeps_active_and_recent_constraints():
    values = np.array([-0.9, -0.4, -0.6, -0.1])
    multipliers = np.array([0.0, 0.0, 2.0, 0.0])
    previous = np.array([1, 3])
    kept = working_set(values, 0.3, previous, multipliers, Settings(keep_factor=1.5))
    # 3 is close, 2 is active, 1 was in the working set and stayed within 0.45.
    assert kept.tolist() == [1, 2, 3]


def test_the_screening_margin_follows_the_steps():
    settings = Settings(screening_margin=0.3, screening_margin_min=0.05)
    now = np.array([0.0, -1.0])
    assert screening_margin(now, None, settings) == 0.3
    moved = np.array([1.0, 0.0])
    assert screening_margin(now, now + 0.001 * moved, settings) == 0.05
    assert screening_margin(now, now + 0.1 * moved, settings) == pytest.approx(0.2)
    assert screening_margin(now, now + moved, settings) == 0.3


def test_the_row_cache():
    settings = Settings(row_refresh="near_active", max_row_age=2, max_row_step=0.1)
    cache = RowCache(2)
    asked = []

    def fetch_at(x):
        def fetch(indices):
            asked.append(indices.tolist())
            return np.array([[float(i), x[0]] for i in indices])

        return fetch

    ranges = np.ones(2)
    far = np.array([False, False])
    x = np.zeros(2)
    rows, computed, reused = cache.rows(
        np.array([0, 1]), x, 0, far, ranges, settings, fetch_at(x)
    )
    assert (computed, reused) == (2, 0)
    x = np.array([0.05, 0.0])  # Moved little: reused.
    rows, computed, reused = cache.rows(
        np.array([0, 1]), x, 1, np.array([True, False]), ranges, settings, fetch_at(x)
    )
    assert (computed, reused) == (1, 1)  # The one close to activity is fresh.
    assert rows[:, 1].tolist() == [0.05, 0.0]
    x = np.array([0.5, 0.0])  # Moved much: computed again.
    _, computed, reused = cache.rows(
        np.array([0, 1]), x, 2, far, ranges, settings, fetch_at(x)
    )
    assert (computed, reused) == (2, 0)
    cache.keep(np.array([1]))
    assert len(cache) == 1


def test_rows_are_asked_for_in_batches():
    problem = hs43().problem
    Optimizer(problem, Settings(row_batch_size=2, max_iter=1)).step()
    # First the row of the largest constraint, for the scale of the screening.
    assert problem.requests == [1, 2]


def test_sparse_rows_give_the_same_iterates():
    dense_run = Optimizer(hs43().problem).run()
    sparse_problem = hs43().problem
    sparse_problem._sparse_rows = True
    sparse_run = Optimizer(sparse_problem).run()
    assert sparse_run.iterations == dense_run.iterations
    assert sparse_run.x == pytest.approx(dense_run.x, abs=1e-12)


def test_equality_constraints():
    # HS 7: min log(1 + x1²) - x2 s.t. (1 + x1²)² + x2² = 4.
    problem = DenseProblem(
        x0=np.array([2.0, 2.0]),
        lower=np.full(2, -5.0),
        upper=np.full(2, 5.0),
        objective=lambda x: float(np.log(1 + x[0] ** 2) - x[1]),
        objective_gradient=lambda x: np.array([2 * x[0] / (1 + x[0] ** 2), -1.0]),
        constraints=lambda x: np.zeros(0),
        constraint_jacobian=lambda x: np.zeros((0, 2)),
        equalities=lambda x: np.array([(1 + x[0] ** 2) ** 2 + x[1] ** 2 - 4]),
        equality_jacobian=lambda x: np.array([[4 * x[0] * (1 + x[0] ** 2), 2 * x[1]]]),
    )
    result = Optimizer(problem, Settings(**GCMMA)).run()
    assert result.status == "converged"
    assert result.x == pytest.approx([0.0, np.sqrt(3)], abs=1e-3)
    assert result.max_constraint <= 1e-5


def test_a_linear_equality_with_mma():
    problem = DenseProblem(
        x0=np.array([0.9, 0.1]),
        lower=np.zeros(2),
        upper=np.ones(2),
        objective=lambda x: float(x @ x),
        objective_gradient=lambda x: 2 * x,
        constraints=lambda x: np.zeros(0),
        constraint_jacobian=lambda x: np.zeros((0, 2)),
        equalities=lambda x: np.array([x.sum() - 1.0]),
        equality_jacobian=lambda x: np.ones((1, 2)),
    )
    result = Optimizer(problem, Settings(dual_solver="lbfgsb")).run()
    assert result.status == "converged"
    assert result.x == pytest.approx([0.5, 0.5], abs=1e-3)


@pytest.mark.parametrize("make", [hs43, synthetic])
def test_float32_rows_find_the_optimum_of_float64_rows(make):
    # The approximations are built around the iterate: float32 rows only round
    # small corrections, and meet the same tolerances.
    tight = {"dual_solver": "lbfgsb"}
    runs = {}
    for dtype in ("float32", "float64"):
        problem = make() if make is synthetic else make().problem
        settings = Settings(**tight, row_dtype=dtype, method="gcmma")
        runs[dtype] = Optimizer(problem, settings).run()
    assert runs["float32"].status == runs["float64"].status == "converged"
    # Both converged: a KKT residual of 1e-3 places x within a few 1e-3.
    assert runs["float32"].x == pytest.approx(runs["float64"].x, abs=5e-3)
