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

try:
    from numba import njit

    from gemseo_lso.core._numba_kernels import curvature_numba
    from gemseo_lso.core._numba_kernels import primal_numba
except ImportError:  # pragma: no cover - Numba is a dependency, kept optional.
    NUMBA = False
else:
    NUMBA = True

IntArray = NDArray[np.int64]


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
    path = np.arange(3)
    greedy(np.array([0, 2, 5, 7]), np.array([0, 1, 0, 1, 2, 1, 2]), path)
