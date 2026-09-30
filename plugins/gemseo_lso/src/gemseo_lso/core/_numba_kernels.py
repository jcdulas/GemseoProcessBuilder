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
