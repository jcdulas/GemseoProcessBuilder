import io

import numpy as np
import pytest
from scipy import sparse
from scipy import stats

from gemseo_lso import DenseProblem
from gemseo_lso import Optimizer
from gemseo_lso import ProblemError
from gemseo_lso import Settings
from gemseo_lso import SettingsError
from gemseo_lso import State
from gemseo_lso.benchmarks.synthetic import LocalConstraints
from gemseo_lso.core import kernels
from gemseo_lso.core.coloring import color
from gemseo_lso.core.coloring import is_valid
from gemseo_lso.core.coloring import widen
from gemseo_lso.core.sparse_jacobian import ColoredJacobian
from gemseo_lso.core.sparse_jacobian import colored_jacobian
from gemseo_lso.core.sparse_jacobian import probe_sparsity
from gemseo_lso.core.sparse_jacobian import recover


def five_points(side):
    """Each cell of a grid with its four neighbours (no wrap)."""
    rows, columns = [], []
    for i in range(side):
        for j in range(side):
            cell = i * side + j
            for di, dj in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
                if 0 <= i + di < side and 0 <= j + dj < side:
                    rows.append(cell)
                    columns.append((i + di) * side + j + dj)
    size = side * side
    return sparse.csr_matrix(
        (np.ones(len(rows), dtype=bool), (rows, columns)), shape=(size, size)
    )


def jacobian_of(problem, coloring, tangent=True):
    return colored_jacobian(
        problem.directional_derivatives if tangent else None,
        lambda x: problem.values(x)[1],
        problem.x0,
        problem.values(problem.x0)[1],
        coloring,
        problem.lower,
        problem.upper,
        1e-6,
    )


def row_errors(problem, matrix):
    true = problem.jacobian.multiply(problem.pattern.astype(float))
    difference = matrix - true
    squares = np.asarray(difference.multiply(difference).sum(axis=1)).ravel()
    norms = np.asarray(true.multiply(true).sum(axis=1)).ravel()
    return np.sqrt(squares / norms)


def run(problem, **settings):
    optimizer = Optimizer(problem, Settings(method="gcmma", **settings))
    reports = list(optimizer)
    return optimizer.result, reports


@pytest.mark.parametrize("margin", [0, 1, 2])
def test_each_coloring_is_valid_on_its_widened_pattern(margin):
    pattern = LocalConstraints(200, grid=False).pattern
    coloring = color(pattern, margin, 2)
    assert coloring.margins == (margin, margin + 1)
    for widening, colors in zip(coloring.margins, coloring.colors, strict=True):
        assert is_valid(widen(pattern, widening), colors)
    # Two columns sharing a row in the same color: invalid.
    assert not is_valid(pattern, np.zeros(200, dtype=np.int64))


def test_a_five_point_stencil_needs_at_most_13_colors_whatever_its_size():
    counts = [color(five_points(side), 0, 1).counts[0] for side in (15, 45)]
    assert max(counts) <= 13
    assert counts[0] == counts[1]
    assert color(five_points(15), 1, 1).counts[0] > counts[0]


def test_the_colorings_put_each_variable_with_other_companions():
    pattern = LocalConstraints(300).pattern
    coloring = color(pattern, 1, 2)

    def companions(colors):
        groups = {c: set(np.flatnonzero(colors == c)) for c in np.unique(colors)}
        return [groups[c] - {j} for j, c in enumerate(colors)]

    first, second = (companions(colors) for colors in coloring.colors)
    changed = np.mean([a != b for a, b in zip(first, second, strict=True)])
    assert changed > 0.9


def test_numba_colors_like_python():
    graph = LocalConstraints(100).pattern.astype(np.int64)
    graph = sparse.csr_matrix(graph.T @ graph)
    order = np.arange(100, dtype=np.int64)
    colors, count = kernels.greedy(graph.indptr, graph.indices, order)
    python = np.full(100, -1, dtype=np.int64)
    python_count = kernels.greedy_python(
        graph.indptr.astype(np.int64), graph.indices.astype(np.int64), order, python
    )
    assert count == python_count
    assert np.array_equal(colors, python)


@pytest.mark.parametrize(("tangent", "tolerance"), [(True, 1e-12), (False, 1e-6)])
def test_the_colored_jacobian_of_a_sparse_problem_is_exact(tangent, tolerance):
    problem = LocalConstraints(200, seed=2)
    coloring = color(problem.pattern, 1, 2)
    jacobian, directions, evaluations = jacobian_of(problem, coloring, tangent)
    assert abs(jacobian.matrix - problem.jacobian).max() < tolerance
    assert jacobian.leakage.max() < tolerance
    assert directions == coloring.total
    assert evaluations == (0 if tangent else coloring.total)


def test_overlap_improves_the_entries_and_estimates_their_error():
    problem = LocalConstraints(400, seed=1, coupling=0.05)
    single, _, _ = jacobian_of(problem, color(problem.pattern, 1, 1))
    overlapping, _, _ = jacobian_of(problem, color(problem.pattern, 1, 2))
    errors = row_errors(problem, overlapping.matrix)
    assert np.median(errors) < 0.8 * np.median(row_errors(problem, single.matrix))
    assert not single.leakage.any()  # One coloring cannot tell.
    # The estimate follows the true error: same order, correlated over the rows.
    assert 0.3 < np.median(overlapping.leakage) / np.median(errors) < 3
    assert stats.spearmanr(errors, overlapping.leakage)[0] > 0.5


def test_leakage_of_a_row_without_entries_in_its_pattern():
    products = np.array([[0.0, 1.0]])
    coloring = color(sparse.csr_matrix(np.array([[True, True]])), 0, 1)
    _, leakage = recover(coloring, products, np.ones(2))
    assert leakage.tolist() == [0.0]


def test_the_hybrid_mode_on_an_exactly_sparse_problem():
    # No leakage: the exact rows of the constraints close to activity only.
    problem = LocalConstraints(100, active_share=0.05, seed=1)
    result, reports = run(problem, jacobian_mode="hybrid")
    assert result.status == "converged"
    assert result.x == pytest.approx(problem.solution, abs=5e-3)
    rows, _ = run(LocalConstraints(100, active_share=0.05, seed=1))
    assert result.row_evaluations < 0.8 * rows.row_evaluations
    colors = color(problem.pattern, 1, 2).total
    assert {report.directional_derivatives for report in reports} == {colors}
    assert result.directional_derivatives == problem.products == colors * len(reports)


def coupled():
    return LocalConstraints(60, active_share=0.05, seed=1, coupling=0.05)


def test_hybrid_mode_with_far_coupling():
    problem = coupled()
    result, _ = run(problem, jacobian_mode="hybrid")
    assert result.status == "converged"
    hybrid_error = np.abs(result.x - problem.solution).max()
    assert hybrid_error < 5e-3
    # Exact rows only for the constraints close to activity (or leaking): the
    # whole working set once it has shrunk to the active ones, fewer rows over
    # the run than the rows mode.
    rows, _ = run(coupled())
    assert result.row_evaluations < 0.8 * rows.row_evaluations


def test_schubert_update():
    rng = np.random.default_rng(0)
    pattern = LocalConstraints(50).pattern
    true = sparse.csr_matrix(pattern.multiply(rng.standard_normal((50, 50))))
    step = rng.standard_normal(50)
    # Linear constraints: an exact Jacobian stays exact.
    exact = ColoredJacobian(true.copy(), np.zeros(50))
    exact.update(step, true @ step)
    assert abs(exact.matrix - true).max() < 1e-12
    # A wrong one meets the secant condition after the step, on its pattern.
    wrong = ColoredJacobian(sparse.csr_matrix(true * 1.1), np.zeros(50))
    wrong.update(step, true @ step)
    assert wrong.matrix @ step == pytest.approx(true @ step, abs=1e-12)
    assert wrong.matrix.nnz == true.nnz


def test_fewer_directional_derivatives_between_colorings():
    problem = LocalConstraints(100, seed=1)
    result, reports = run(problem, jacobian_mode="hybrid", jacobian_refresh=3)
    assert result.status == "converged"
    assert result.x == pytest.approx(problem.solution, abs=5e-3)
    new = [report.directional_derivatives > 0 for report in reports]
    assert new[:4] == [True, False, False, True]
    colors = color(problem.pattern, 1, 2).total
    assert result.directional_derivatives == colors * sum(new)


def test_probe_sparsity():
    exact = LocalConstraints(200, seed=1)
    probe = probe_sparsity(exact, exact.x0, np.arange(0, 200, 20))
    assert probe.outside.max() == 0
    assert probe.error.max() < 1e-12
    assert probe.colors == color(exact.pattern, 1, 2).total
    coupled = LocalConstraints(200, seed=1, coupling=0.05)
    probe = probe_sparsity(coupled, coupled.x0, np.arange(0, 200, 20))
    assert probe.outside.min() > 0.01
    assert probe.error.min() > 0
    assert probe.leakage.min() > 0


def test_the_rows_mode_by_default_even_with_a_pattern():
    assert Settings().jacobian_mode == "rows"
    problem = LocalConstraints(100, seed=1)
    result, _ = run(problem)
    assert result.directional_derivatives == problem.products == 0
    assert result.row_evaluations > 0


def dense_problem(pattern=None):
    return DenseProblem(
        x0=np.full(2, 0.5),
        lower=np.zeros(2),
        upper=np.ones(2),
        objective=lambda x: float(x @ x),
        objective_gradient=lambda x: 2 * x,
        constraints=lambda x: np.array([0.5 - x[0], 0.4 - x[1]]),
        constraint_jacobian=lambda x: -np.eye(2),
        pattern=pattern,
    )


def test_the_hybrid_mode_needs_a_sparse_pattern():
    hybrid = Settings(jacobian_mode="hybrid")
    with pytest.raises(ProblemError, match="sparsity pattern"):
        Optimizer(dense_problem(), hybrid)
    with pytest.raises(ProblemError, match=r"scipy\.sparse"):
        Optimizer(dense_problem(np.eye(2, dtype=bool)), hybrid)
    with pytest.raises(ProblemError, match="shape"):
        Optimizer(dense_problem(sparse.eye(3, dtype=bool, format="csr")), hybrid)
    with pytest.raises(ProblemError, match="depend on no variable"):
        Optimizer(
            dense_problem(sparse.csr_matrix(np.array([[True, False], [False, False]]))),
            hybrid,
        )
    # Every row from the colored Jacobian: removed (plan 69).
    for mode in ("colored", "auto"):
        with pytest.raises(SettingsError, match="jacobian_mode"):
            Settings(jacobian_mode=mode)  # type: ignore[arg-type]


def test_finite_differences_without_a_tangent_mode():
    problem = dense_problem(sparse.eye(2, dtype=bool, format="csr"))
    optimizer = Optimizer(problem, Settings(jacobian_mode="hybrid", method="gcmma"))
    result = optimizer.run()
    assert result.status == "converged"
    assert result.x == pytest.approx([0.5, 0.4], abs=1e-3)
    # One evaluation of the values per color and iteration, beyond the steps.
    assert result.evaluations > result.directional_derivatives


def test_a_saved_state_resumes_exactly_in_the_hybrid_mode():
    settings = Settings(method="gcmma", jacobian_mode="hybrid")
    straight = Optimizer(LocalConstraints(100, seed=1, coupling=0.05), settings)
    for _ in range(6):
        straight.step()
    first = Optimizer(LocalConstraints(100, seed=1, coupling=0.05), settings)
    for _ in range(3):
        first.step()
    buffer = io.BytesIO()
    first.state.save(buffer)
    buffer.seek(0)
    resumed = Optimizer(
        LocalConstraints(100, seed=1, coupling=0.05), settings, State.load(buffer)
    )
    for _ in range(3):
        resumed.step()
    assert np.array_equal(resumed.state.x, straight.state.x)
    assert (
        resumed.state.directional_derivatives == straight.state.directional_derivatives
    )
