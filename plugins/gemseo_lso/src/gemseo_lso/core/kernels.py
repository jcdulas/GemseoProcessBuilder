"""The loops over the variables of an evaluation of the dual, fused (spec § 3.7).

At 10⁶ variables, an evaluation of the dual was 80 % NumPy operations on
vectors of the size of the design space, each creating a temporary and
running on one core, while the products with the sparse rows took 2 %. Here
each loop is one pass over the variables, on every core with Numba
(``parallel=True``), or, without Numba, the same computation in NumPy.

Both give the same results (tests): Numba is an acceleration, not a
requirement.
"""

import numpy as np
from numpy.typing import NDArray

from gemseo_lso.core.arrays import Array
from gemseo_lso.core.arrays import Rows
from gemseo_lso.core.arrays import is_sparse
from gemseo_lso.core.arrays import rows_times
from gemseo_lso.core.arrays import times_rows

try:
    from numba import get_num_threads
    from numba import njit

    from gemseo_lso.core._numba_kernels import combine_numba
    from gemseo_lso.core._numba_kernels import curvature_numba
    from gemseo_lso.core._numba_kernels import gram_numba
    from gemseo_lso.core._numba_kernels import matvec_numba
    from gemseo_lso.core._numba_kernels import primal_numba
    from gemseo_lso.core._numba_kernels import rmatvec_numba
    from gemseo_lso.core._numba_kernels import sum_parts_numba
except ImportError:  # pragma: no cover - Numba is a dependency, kept optional.
    NUMBA = False
else:
    NUMBA = True

IntArray = NDArray[np.int64]

PARALLEL_NONZEROS = 100_000
"""The nonzeros of the rows from which their products run on every core: below,
SciPy's, on one core, are as fast and give the very same sums."""


def _parallel(rows: Rows) -> bool:
    """Whether the products with these rows run in parallel.

    Numba, sparse rows in CSR and float64, and enough of them: the float32 ones
    keep SciPy's sums.
    """
    return bool(
        NUMBA
        and is_sparse(rows)
        and rows.format == "csr"
        and rows.dtype == np.float64
        and rows.nnz >= PARALLEL_NONZEROS
    )


def times(rows: Rows, vector: Array) -> Array:
    """``rows @ vector``, as ``arrays.rows_times``, on every core for large rows.

    The evaluations of the dual are 75 % these products when the working set
    holds every constraint (a profile of a run started from a design violating
    them all): SciPy runs them on one core.
    """
    if _parallel(rows):
        out = np.empty(rows.shape[0])
        matvec_numba(
            rows.indptr,
            rows.indices,
            rows.data,
            np.ascontiguousarray(vector, dtype=np.float64),
            out,
        )
        return out
    return rows_times(rows, vector)


def gram(rows: Rows, weight: Array) -> Array | None:
    """The lower triangle of ``rows diag(weight) rowsᵀ``, dense, on every core.

    ``None`` if it cannot be computed this way. The upper triangle is zero: the
    matrix is symmetric and the Cholesky factorization reads one triangle.

    The matrix of the Newton system of the dual (``S D⁻¹ Sᵀ``). Only sparse rows
    in CSR and float64 are handled, with Numba: the nonzeros are visited, in
    parallel, in 2 to 47 ms where SciPy's product of sparse matrices took 0.2 to
    0.6 s on rows of 1,300 to 3,000 constraints. The matrix is dense, of the
    square of the number of rows.
    """
    if not (NUMBA and is_sparse(rows) and rows.format == "csr"):
        return None
    if rows.dtype != np.float64:
        return None
    columns = rows.tocsc()
    columns.sort_indices()  # The loop stops at the diagonal.
    size = rows.shape[0]
    out = np.empty((size, size))
    gram_numba(
        rows.indptr,
        rows.indices,
        rows.data,
        columns.indptr,
        columns.indices,
        columns.data,
        np.ascontiguousarray(weight, dtype=np.float64),
        out,
    )
    return out


def combine(
    indptr: IntArray,
    indices: IntArray,
    absolute: Array,
    signed: Array,
    left: Array,
    right: Array,
) -> Array:
    """``absolute left[j] + signed right[j]`` for each entry of columns ``j``.

    The data of ``|G| diag(left) + G diag(right)``, for ``|G|`` and ``G`` with the
    same nonzeros, in one pass: six passes and as many copies in NumPy, 20 ms on
    500,000 entries.
    """
    if NUMBA:
        out = np.empty(absolute.size)
        combine_numba(indptr, indices, absolute, signed, left, right, out)
        return out
    result: Array = absolute * left[indices] + signed * right[indices]
    return result


def times_transposed(vector: Array, rows: Rows, dtype: type | None = float) -> Array:
    """``vector @ rows``, as ``arrays.times_rows``, on every core for large rows.

    Each core adds a block of the rows into a line of its own, the lines are then
    added: no copy of the rows, transposed, is kept.
    """
    if _parallel(rows):
        blocks = int(get_num_threads())
        parts = np.empty((blocks, rows.shape[1]))
        rmatvec_numba(
            rows.indptr,
            rows.indices,
            rows.data,
            np.ascontiguousarray(vector, dtype=np.float64),
            parts,
        )
        out = np.empty(rows.shape[1])
        sum_parts_numba(parts, out)
        return out
    return times_rows(vector, rows, dtype)


def primal_numpy(
    x0: Array,
    lower: Array,
    upper: Array,
    alpha: Array,
    beta: Array,
    inverse_ranges: Array,
    ux2: Array,
    xl2: Array,
    p0: Array,
    q0: Array,
    absolute: Array,
    signed: Array,
    rho: float,
    x: Array,
    difference: Array,
    total: Array,
) -> tuple[float, float]:
    """The minimizer of the Lagrangian of the subproblem, and its steps.

    Args:
        x0: The iterate ``x_k``.
        lower: The lower asymptotes.
        upper: The upper asymptotes.
        alpha: The lower bounds of the subproblem.
        beta: The upper bounds of the subproblem.
        inverse_ranges: ``1 / range`` of the variables.
        ux2: ``(u - x_k)²``.
        xl2: ``(x_k - l)²``.
        p0: ``p`` of the objective.
        q0: ``q`` of the objective.
        absolute: ``λᵀ|G|``.
        signed: ``λᵀG``.
        rho: ``λ·rho``.
        x: Where to write the minimizer.
        difference: Where to write ``A - B``, in the precision of the rows.
        total: Where to write ``A + B``, in the precision of the rows.

    Returns:
        ``Σ p0/ux2 A - q0/xl2 B`` (the change of the approximated objective) and
        ``Σ (A - B) / range`` (the change of the curvature terms).
    """
    term = rho * inverse_ranges
    p = p0 + ux2 * (0.501 * absolute + 0.5 * signed + term)
    q = q0 + xl2 * (0.501 * absolute - 0.5 * signed + term)
    root_p, root_q = np.sqrt(p), np.sqrt(q)
    np.clip((root_p * lower + root_q * upper) / (root_p + root_q), alpha, beta, out=x)
    step = x - x0
    a = (upper - x0) * step / (upper - x)
    b = (x0 - lower) * step / (x - lower)
    np.subtract(a, b, out=difference)
    np.add(a, b, out=total)
    objective = float(np.sum(p0 / ux2 * a - q0 / xl2 * b))
    return objective, float(difference @ inverse_ranges)


def curvature_numpy(
    x: Array,
    lower: Array,
    upper: Array,
    alpha: Array,
    beta: Array,
    inverse_ranges: Array,
    ux2: Array,
    xl2: Array,
    p0: Array,
    q0: Array,
    absolute: Array,
    signed: Array,
    rho: float,
    inverse: Array,
    left: Array,
    right: Array,
    w: Array,
) -> None:
    """The vectors of the Hessian of the dual at a minimizer ``x``.

    Writes ``D⁻¹`` (zero at the bounds of the subproblem), the column factors
    ``0.501 (A' - B')`` and ``0.5 (A' + B')`` of the Jacobian of the
    approximated constraints, and ``w = (A' - B') / range``.
    """
    term = rho * inverse_ranges
    p = p0 + ux2 * (0.501 * absolute + 0.5 * signed + term)
    q = q0 + xl2 * (0.501 * absolute - 0.5 * signed + term)
    curvature = 2 * p / (upper - x) ** 3 + 2 * q / (x - lower) ** 3
    free = (x > alpha) & (x < beta)
    inverse[:] = np.where(free, 1.0 / curvature, 0.0)
    a = ux2 / (upper - x) ** 2
    b = xl2 / (x - lower) ** 2
    np.multiply(0.501, a - b, out=left)
    np.multiply(0.5, a + b, out=right)
    np.multiply(a - b, inverse_ranges, out=w)


def _in_double(arguments: tuple[object, ...]) -> list[object]:
    """The arguments, with the products ``λᵀ|G|`` and ``λᵀG`` in float64.

    They come in the precision of the rows; Numba reads float32 and computes in
    float64, NumPy would compute in float32.
    """
    converted = list(arguments)
    for index in (PRODUCTS, PRODUCTS + 1):
        converted[index] = np.asarray(converted[index], dtype=float)
    return converted


PRODUCTS = 10
"""The position of ``absolute`` in the arguments of the kernels."""


def primal(*arguments: object) -> tuple[float, float]:
    """``primal_numpy``, compiled by Numba when it is installed."""
    if NUMBA:
        objective, curvature = primal_numba(*arguments)
        return float(objective), float(curvature)
    return primal_numpy(*_in_double(arguments))  # type: ignore[arg-type]


def curvature(*arguments: object) -> None:
    """``curvature_numpy``, compiled by Numba when it is installed."""
    if NUMBA:
        curvature_numba(*arguments)
    else:
        curvature_numpy(*_in_double(arguments))  # type: ignore[arg-type]


def greedy_python(
    indptr: IntArray, indices: IntArray, order: IntArray, colors: IntArray
) -> int:
    """Color the vertices of a graph greedily, in an order.

    Each vertex takes the smallest color none of its neighbours has yet.

    Args:
        indptr: The adjacency of the graph, in CSR: the neighbours of ``j`` are
            ``indices[indptr[j]:indptr[j + 1]]`` (``j`` itself may be among them).
        indices: See ``indptr``.
        order: The vertices, in the order they are colored.
        colors: Where to write the color of each vertex, filled with -1.

    Returns:
        The number of colors.
    """
    # For each color, the last vertex it was forbidden to.
    forbidden = np.full(order.size + 1, -1, dtype=np.int64)
    count = 0
    for position in range(order.size):
        vertex = order[position]
        for k in range(indptr[vertex], indptr[vertex + 1]):
            color = colors[indices[k]]
            if color >= 0:
                forbidden[color] = vertex
        color = 0
        while forbidden[color] == vertex:
            color += 1
        colors[vertex] = color
        count = max(count, color + 1)
    return count


if NUMBA:
    greedy_numba = njit(cache=True)(greedy_python)


def greedy(
    indptr: IntArray, indices: IntArray, order: IntArray
) -> tuple[IntArray, int]:
    """``greedy_python``, compiled by Numba when it is installed.

    A loop over the vertices and their neighbours: 10⁶ vertices of 13
    neighbours take seconds in Python, milliseconds compiled.

    Returns:
        The color of each vertex, and the number of colors.
    """
    colors = np.full(order.size, -1, dtype=np.int64)
    arguments = (
        indptr.astype(np.int64, copy=False),
        indices.astype(np.int64, copy=False),
        order.astype(np.int64, copy=False),
        colors,
    )
    count = greedy_numba(*arguments) if NUMBA else greedy_python(*arguments)
    return colors, int(count)


def warm_up() -> None:
    """Compile the kernels (or load them from Numba's cache) on tiny graphs and arrays.

    Once for rows in float64, once for rows in float32.
    """
    size = 2
    ones = np.ones(size)
    zeros = np.zeros(size)
    out = [np.empty(size) for _ in range(4)]
    for products in (zeros, zeros.astype(np.float32)):
        steps = [np.empty(size, products.dtype) for _ in range(2)]
        primal(zeros, -ones, ones, -ones, ones, ones, ones, ones, ones, ones,
               products, products, 0.0, out[0], *steps)  # fmt: skip
        curvature(zeros, -ones, ones, -ones, ones, ones, ones, ones, ones, ones,
                  products, products, 0.0, *out)  # fmt: skip
    if NUMBA:  # The products with the rows, once for each loop.
        rows = np.array([[1.0, 0.0], [2.0, 3.0]])
        from scipy import sparse

        matrix = sparse.csr_matrix(rows)
        matvec_numba(matrix.indptr, matrix.indices, matrix.data, ones, np.empty(2))
        parts = np.empty((2, 2))
        rmatvec_numba(matrix.indptr, matrix.indices, matrix.data, ones, parts)
        sum_parts_numba(parts, np.empty(2))
        gram_numba(
            matrix.indptr,
            matrix.indices,
            matrix.data,
            matrix.indptr,
            matrix.indices,
            matrix.data,
            ones,
            np.empty((2, 2)),
        )
        combine_numba(
            matrix.indptr, matrix.indices, matrix.data, matrix.data, ones, ones,
            np.empty(matrix.nnz),
        )  # fmt: skip
    path = np.arange(3)
    greedy(np.array([0, 2, 5, 7]), np.array([0, 1, 0, 1, 2, 1, 2]), path)
