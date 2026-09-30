import numpy as np
import pytest

from gemseo_lso.core import Settings
from gemseo_lso.core.approximation import Approximation
from gemseo_lso.core.approximation import asymptotes
from gemseo_lso.core.approximation import move_limits
from gemseo_lso.core.dual import solve_dual
from gemseo_lso.core.dual import solve_interior_point


def approximation(n=30, m=5, seed=0, rho=1e-5):
    rng = np.random.default_rng(seed)
    x = rng.uniform(0.2, 0.8, n)
    lower, upper = asymptotes(x, None, None, None, None, np.ones(n), Settings())
    alpha, beta = move_limits(x, lower, upper, np.zeros(n), np.ones(n), Settings())
    return Approximation(
        x=x,
        lower_asymptote=lower,
        upper_asymptote=upper,
        alpha=alpha,
        beta=beta,
        ranges=np.ones(n),
        objective=1.0,
        objective_gradient=rng.standard_normal(n),
        constraints=rng.uniform(-0.5, 0.2, m),
        rows=rng.standard_normal((m, n)),
        objective_rho=rho,
        constraint_rho=np.full(m, rho),
    )


def test_the_approximations_match_value_and_gradient_at_the_iterate():
    a = approximation(rho=0.3)
    assert a.objective_value(a.x) == pytest.approx(a.objective)
    assert a.constraint_values(a.x) == pytest.approx(a.constraints)
    step = 1e-6
    for j in (0, 7, 29):
        shifted = a.x.copy()
        shifted[j] += step
        slopes = (a.constraint_values(shifted) - a.constraints) / step
        assert slopes == pytest.approx(a.rows[:, j], rel=1e-4, abs=1e-4)
        slope = (a.objective_value(shifted) - a.objective) / step
        assert slope == pytest.approx(a.objective_gradient[j], rel=1e-4, abs=1e-4)


def test_the_explicit_terms_give_the_same_approximations():
    a = approximation(rho=0.2)
    p, q, r, p0, q0, r0 = a.explicit()
    x = a.x + 0.05
    up, low = a.upper_asymptote, a.lower_asymptote
    assert r + p @ (1 / (up - x)) + q @ (1 / (x - low)) == pytest.approx(
        a.constraint_values(x)
    )
    assert r0 + np.sum(p0 / (up - x) + q0 / (x - low)) == pytest.approx(
        a.objective_value(x)
    )


def test_the_gradient_of_the_dual():
    a = approximation()
    cost = np.full(a.size, 1000.0)
    multipliers = np.array([0.1, 0.5, 1.0, 0.0, 2.0])
    value, gradient, _, _ = a.dual(multipliers, cost, 1.0)
    for i in range(a.size):
        shifted = multipliers.copy()
        shifted[i] += 1e-7
        assert (a.dual(shifted, cost, 1.0)[0] - value) / 1e-7 == pytest.approx(
            gradient[i], rel=1e-4, abs=1e-5
        )


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_both_solvers_find_the_kkt_point(seed):
    a = approximation(seed=seed)
    by_dual = solve_dual(a, 1000.0, 1.0, np.zeros(a.size))
    by_interior = solve_interior_point(a, 1000.0, 1.0)
    assert by_dual.x == pytest.approx(by_interior.x, abs=1e-4)
    assert by_dual.multipliers == pytest.approx(by_interior.multipliers, abs=1e-3)
    # Feasible (with the elastic variables) and complementary.
    slack = a.constraint_values(by_dual.x) - by_dual.elastic
    assert slack.max() <= 1e-5
    assert np.abs(by_dual.multipliers * slack).max() <= 1e-5
    assert np.all((by_dual.x >= a.alpha) & (by_dual.x <= a.beta))


def test_asymptotes_widen_narrow_and_stay_in_range():
    settings = Settings()
    ranges = np.ones(3)
    x = np.array([0.5, 0.5, 0.5])
    first = asymptotes(x, None, None, None, None, ranges, settings)
    assert first[0] == pytest.approx(x - 0.5)
    previous, before = np.array([0.4, 0.6, 0.5]), np.array([0.3, 0.5, 0.5])
    lower, upper = asymptotes(x, previous, before, *first, ranges, settings)
    # Same way twice: wider; oscillating: narrower; still: unchanged.
    assert x[0] - lower[0] == pytest.approx(1.2 * (previous[0] - first[0][0]))
    assert x[1] - lower[1] == pytest.approx(0.7 * (previous[1] - first[0][1]))
    assert upper[2] - x[2] == pytest.approx(0.5)
    far = asymptotes(x, previous, before, x - 100, x + 100, ranges, settings)
    assert far[0] == pytest.approx(x - 10) and far[1] == pytest.approx(x + 10)


def test_move_limits():
    settings = Settings(move_limit=0.1)
    x = np.array([0.05, 0.5])
    alpha, beta = move_limits(x, x - 0.5, x + 0.5, np.zeros(2), np.ones(2), settings)
    assert alpha == pytest.approx([0.0, 0.4])
    assert beta == pytest.approx([0.15, 0.6])


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("sparse_rows", [False, True])
def test_newton_finds_the_kkt_point(seed, sparse_rows):
    from scipy import sparse

    from gemseo_lso.core.dual import solve_newton

    a = approximation(seed=seed, rho=0.05)
    if sparse_rows:
        a = approximation(seed=seed, rho=0.05)
        a.rows = sparse.csr_matrix(a.rows)
        a.__post_init__()
    by_newton = solve_newton(a, 1000.0, 1.0, np.zeros(a.size), tolerance=1e-9)
    by_interior = solve_interior_point(a, 1000.0, 1.0)
    assert by_newton.x == pytest.approx(by_interior.x, abs=1e-6)
    assert by_newton.multipliers == pytest.approx(by_interior.multipliers, abs=1e-5)


def test_newton_needs_fewer_dual_evaluations():
    from gemseo_lso import Optimizer
    from gemseo_lso.benchmarks.synthetic import LocalConstraints
    from gemseo_lso.core.approximation import Approximation

    counts = {}
    original = Approximation.dual
    for solver in ("lbfgsb", "newton"):
        calls = [0]

        def counted(self, *args, calls=calls, **kwargs):
            calls[0] += 1
            return original(self, *args, **kwargs)

        Approximation.dual = counted
        try:
            problem = LocalConstraints(400, active_share=0.02, seed=0)
            settings = Settings(method="gcmma", dual_solver=solver)
            result = Optimizer(problem, settings).run()
        finally:
            Approximation.dual = original
        assert result.status == "converged"
        assert result.x == pytest.approx(problem.solution, abs=2e-3)
        counts[solver] = calls[0]
    assert counts["newton"] < counts["lbfgsb"]


def test_the_numba_kernels_compute_what_numpy_does():
    from gemseo_lso.core import kernels

    if not kernels.NUMBA:
        pytest.skip("Numba is not installed.")
    a = approximation(n=50, m=4, seed=3, rho=0.1)
    rng = np.random.default_rng(3)
    # λᵀ|G| bounds |λᵀG|.
    absolute = rng.random(50)
    signed = rng.uniform(-1.0, 1.0, 50) * absolute
    vectors = a._vectors()
    by_numpy = [np.empty(50) for _ in range(3)]
    by_numba = [np.empty(50) for _ in range(3)]
    sums_numpy = kernels.primal_numpy(a.x, *vectors, absolute, signed, 0.3, *by_numpy)
    sums_numba = kernels.primal(a.x, *vectors, absolute, signed, 0.3, *by_numba)
    assert sums_numba == pytest.approx(sums_numpy, rel=1e-12)
    for mine, theirs in zip(by_numba, by_numpy, strict=True):
        assert mine == pytest.approx(theirs, rel=1e-12, abs=1e-15)
    x = by_numpy[0]
    curvature_numpy = [np.empty(50) for _ in range(4)]
    curvature_numba = [np.empty(50) for _ in range(4)]
    kernels.curvature_numpy(x, *vectors, absolute, signed, 0.3, *curvature_numpy)
    kernels.curvature(x, *vectors, absolute, signed, 0.3, *curvature_numba)
    for mine, theirs in zip(curvature_numba, curvature_numpy, strict=True):
        assert mine == pytest.approx(theirs, rel=1e-12, abs=1e-15)
