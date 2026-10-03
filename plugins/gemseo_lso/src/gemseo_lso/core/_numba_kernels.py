"""The fused loops of ``kernels``, compiled by Numba, on every core.

Separate so that the rest of the core type-checks strictly: Numba's
``prange`` has no type information. Mirrors ``kernels.primal_numpy`` and
``kernels.curvature_numpy``, which document the arguments.

The loops read more than they compute: at 10⁶ variables, ``primal_numba``
reads about 90 MB per call, near the memory bandwidth. Hence
``error_model="numpy"`` (no check of the divisions, which would keep the loops
from being vectorized; NumPy's infinities instead, as in ``kernels``),
``fastmath`` limited to the reordering of the sums (no assumption on NaNs or
infinities), and ``primal_numba`` computing ``(u - x_k)²`` and ``(x_k - l)²``
instead of reading them: 3.65 ms to 2.88 ms a call.
"""

import numpy as np
from numba import njit
from numba import prange

KERNEL = {
    "parallel": True,
    "cache": True,
    "error_model": "numpy",
    "fastmath": {"reassoc", "contract"},
}
"""The options of both kernels."""


@njit(**KERNEL)
def primal_numba(
    x0,
    lower,
    upper,
    alpha,
    beta,
    inverse_ranges,
    ux2,
    xl2,
    p0,
    q0,
    absolute,
    signed,
    rho,
    x,
    difference,
    total,
):
    objective = 0.0
    curvature = 0.0
    for j in prange(x0.size):
        to_upper = upper[j] - x0[j]
        to_lower = x0[j] - lower[j]
        term = rho * inverse_ranges[j]
        p = p0[j] + to_upper * to_upper * (0.501 * absolute[j] + 0.5 * signed[j] + term)
        q = q0[j] + to_lower * to_lower * (0.501 * absolute[j] - 0.5 * signed[j] + term)
        root_p = np.sqrt(p)
        root_q = np.sqrt(q)
        value = (root_p * lower[j] + root_q * upper[j]) / (root_p + root_q)
        value = min(max(value, alpha[j]), beta[j])
        x[j] = value
        step = value - x0[j]
        a = (upper[j] - x0[j]) * step / (upper[j] - value)
        b = (x0[j] - lower[j]) * step / (value - lower[j])
        difference[j] = a - b
        total[j] = a + b
        objective += (
            p0[j] / (to_upper * to_upper) * a - q0[j] / (to_lower * to_lower) * b
        )
        curvature += (a - b) * inverse_ranges[j]
    return objective, curvature


@njit(**KERNEL)
def curvature_numba(
    x,
    lower,
    upper,
    alpha,
    beta,
    inverse_ranges,
    ux2,
    xl2,
    p0,
    q0,
    absolute,
    signed,
    rho,
    inverse,
    left,
    right,
    w,
):
    for j in prange(x.size):
        term = rho * inverse_ranges[j]
        p = p0[j] + ux2[j] * (0.501 * absolute[j] + 0.5 * signed[j] + term)
        q = q0[j] + xl2[j] * (0.501 * absolute[j] - 0.5 * signed[j] + term)
        to_upper = upper[j] - x[j]
        to_lower = x[j] - lower[j]
        if alpha[j] < x[j] < beta[j]:
            inverse[j] = 1.0 / (2 * p / to_upper**3 + 2 * q / to_lower**3)
        else:
            inverse[j] = 0.0
        a = ux2[j] / to_upper**2
        b = xl2[j] / to_lower**2
        left[j] = 0.501 * (a - b)
        right[j] = 0.5 * (a + b)
        w[j] = (a - b) * inverse_ranges[j]


@njit(parallel=True, cache=True)
def matvec_numba(indptr, indices, data, vector, out):  # type: ignore[no-untyped-def]
    """``out = A @ vector`` for ``A`` in CSR: one row per iteration, on every core."""
    for i in prange(out.size):
        total = 0.0
        for k in range(indptr[i], indptr[i + 1]):
            total += data[k] * vector[indices[k]]
        out[i] = total


@njit(parallel=True, cache=True)
def rmatvec_numba(indptr, indices, data, vector, parts):  # type: ignore[no-untyped-def]
    """The partial sums of ``vector @ A`` for ``A`` in CSR.

    The rows are cut in as many blocks as ``parts`` has lines; each block adds
    its rows, the ones whose multiplier is not zero, in a line of its own, so
    that no two cores write the same place. ``sum_parts_numba`` adds the lines.
    """
    blocks = parts.shape[0]
    rows = indptr.size - 1
    for block in prange(blocks):
        parts[block, :] = 0.0
        for i in range(block * rows // blocks, (block + 1) * rows // blocks):
            weight = vector[i]
            if weight != 0.0:
                for k in range(indptr[i], indptr[i + 1]):
                    parts[block, indices[k]] += data[k] * weight


@njit(parallel=True, cache=True)
def sum_parts_numba(parts, out):  # type: ignore[no-untyped-def]
    """``out`` is the sum of the lines of ``parts``, one variable per iteration."""
    for j in prange(out.size):
        total = 0.0
        for block in range(parts.shape[0]):
            total += parts[block, j]
        out[j] = total


@njit(parallel=True, cache=True)
def gram_numba(row_ptr, row_idx, row_data, col_ptr, col_idx, col_data, weight, out):  # type: ignore[no-untyped-def]
    """The lower triangle of ``A diag(weight) Aᵀ``, for ``A`` in CSR and in CSC.

    ``row_*`` is ``A`` in CSR, ``col_*`` the same in CSC with its row indices
    sorted. One row of ``out`` per iteration: only the nonzeros of ``A`` are
    visited (for each entry ``(i, j)``, the column ``j`` down to the row ``i``,
    the matrix being symmetric), and no two cores write the same row. The part of
    ``out`` above the diagonal is zero. A dense product multiplies the zeros too;
    SciPy's product of sparse matrices runs on one core.
    """
    size = out.shape[0]
    for turn in prange(size):
        # The work of a row grows with its index (the loop stops at the diagonal):
        # taken from both ends, in turn, each core gets as much as the others.
        i = turn // 2 if turn % 2 == 0 else size - 1 - turn // 2
        out[i, :] = 0.0
        for k in range(row_ptr[i], row_ptr[i + 1]):
            j = row_idx[k]
            scaled = row_data[k] * weight[j]
            if scaled != 0.0:
                for kk in range(col_ptr[j], col_ptr[j + 1]):
                    other = col_idx[kk]
                    if other > i:
                        break
                    out[i, other] += scaled * col_data[kk]


@njit(parallel=True, cache=True)
def combine_numba(indptr, indices, absolute, signed, left, right, out):  # type: ignore[no-untyped-def]
    """``out[k] = absolute[k] left[j] + signed[k] right[j]``; ``j`` is the column."""
    for i in prange(indptr.size - 1):
        for k in range(indptr[i], indptr[i + 1]):
            j = indices[k]
            out[k] = absolute[k] * left[j] + signed[k] * right[j]
