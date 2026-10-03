"""The products with the rows of the dual run on every core, with the same sums."""

import logging

import numpy as np
import pytest
from scipy import sparse
from test_lso_live import scenario

from gemseo_lso.core import kernels
from gemseo_lso.core.arrays import rows_times
from gemseo_lso.core.arrays import times_rows

logging.getLogger("gemseo").setLevel(logging.WARNING)
logging.getLogger("gemseo_lso").setLevel(logging.WARNING)

pytestmark = pytest.mark.skipif(not kernels.NUMBA, reason="Numba is not installed")


def random_rows(m=40, n=60, dtype=np.float64, seed=0):
    return sparse.random(
        m, n, density=0.2, format="csr", random_state=seed, dtype=dtype
    )


@pytest.fixture
def every_product_in_parallel(monkeypatch):
    """The parallel products even for the small rows of a test."""
    monkeypatch.setattr(kernels, "PARALLEL_NONZEROS", 1)


def test_the_products_give_the_sums_of_scipy(every_product_in_parallel):
    rows = random_rows()
    rng = np.random.default_rng(1)
    vector = rng.standard_normal(60)
    multipliers = np.abs(rng.standard_normal(40))
    multipliers[rng.random(40) < 0.4] = 0.0  # Only the working set has a multiplier.
    np.testing.assert_allclose(
        kernels.times(rows, vector), rows_times(rows, vector), rtol=1e-12
    )
    np.testing.assert_allclose(
        kernels.times_transposed(multipliers, rows),
        times_rows(multipliers, rows),
        rtol=1e-12,
    )


def test_the_products_by_blocks_cover_every_row(every_product_in_parallel):
    # More blocks than rows, and one row: no row is missed or added twice.
    for m in (1, 2, 3, 17):
        rows = random_rows(m=m, n=9)
        multipliers = np.arange(1.0, m + 1)
        np.testing.assert_allclose(
            kernels.times_transposed(multipliers, rows),
            times_rows(multipliers, rows),
            rtol=1e-12,
        )


@pytest.mark.parametrize(
    "rows",
    [
        random_rows().toarray(),  # Dense: BLAS already runs on every core.
        random_rows().tocsc(),
        random_rows(dtype=np.float32),  # Its sums stay SciPy's.
    ],
    ids=["dense", "csc", "float32"],
)
def test_only_large_float64_csr_rows_run_in_parallel(rows, every_product_in_parallel):
    assert not kernels._parallel(rows)


def test_small_rows_keep_the_products_of_scipy():
    assert not kernels._parallel(random_rows())  # Far under the threshold.
    assert kernels._parallel(random_rows(m=600, n=1000))


def test_a_run_gives_the_same_iterates_with_parallel_products(monkeypatch):
    def run(threshold):
        monkeypatch.setattr(kernels, "PARALLEL_NONZEROS", threshold)
        study = scenario()
        study.execute(algo_name="LSO_MMA", max_iter=8)
        database = study.formulation.optimization_problem.database
        return np.array(
            [
                database.get_function_value("f", database.get_x_vect(i + 1))
                for i in range(len(database))
            ]
        )

    calls = []
    original = kernels.matvec_numba
    monkeypatch.setattr(
        kernels, "matvec_numba", lambda *args: calls.append(1) or original(*args)
    )
    parallel = run(1)
    if not calls:
        pytest.skip("the rows of this problem are not sparse: no parallel product")
    sequential = run(10**12)
    np.testing.assert_allclose(parallel, sequential, rtol=1e-8)


def test_the_gram_matrix_is_the_product_of_scipy():
    rows = random_rows(m=40, n=60)
    weight = np.abs(np.random.default_rng(2).standard_normal(60))
    weight[::3] = 0.0  # The variables at a limit of their move.
    expected = (rows.multiply(weight.reshape(1, -1)) @ rows.T).toarray()
    gram = kernels.gram(rows, weight)
    # The lower triangle: the matrix is symmetric, Cholesky reads one triangle.
    np.testing.assert_allclose(np.tril(gram), np.tril(expected), rtol=1e-12, atol=1e-12)
    np.testing.assert_array_equal(np.triu(gram, 1), 0.0)


def test_the_gram_matrix_of_one_row_and_of_no_weight():
    rows = random_rows(m=1, n=9)
    assert kernels.gram(rows, np.ones(9)).shape == (1, 1)
    np.testing.assert_array_equal(kernels.gram(random_rows(), np.zeros(60)), 0.0)


@pytest.mark.parametrize(
    "rows",
    [
        random_rows().toarray(),
        random_rows().tocsc(),
        random_rows(dtype=np.float32),
    ],
    ids=["dense", "csc", "float32"],
)
def test_the_gram_matrix_is_for_float64_rows_in_csr_only(rows):
    assert kernels.gram(rows, np.ones(60)) is None


def test_the_data_of_the_curvature_pattern_are_combined_in_one_pass():
    rows = random_rows(m=30, n=50)
    rng = np.random.default_rng(3)
    left, right = rng.standard_normal(50), rng.standard_normal(50)
    absolute = abs(rows)
    expected = absolute.multiply(left.reshape(1, -1)) + rows.multiply(
        right.reshape(1, -1)
    )
    combined = kernels.combine(
        rows.indptr, rows.indices, absolute.data, rows.data, left, right
    )
    from scipy import sparse

    pattern = sparse.csr_matrix((combined, rows.indices, rows.indptr), shape=rows.shape)
    np.testing.assert_allclose(pattern.toarray(), expected.toarray(), rtol=1e-12)
