"""The MMA and GCMMA approximations (spec § 3.6).

From Svanberg, *The method of moving asymptotes* (1987), and *A class of
globally convergent optimization methods based on conservative convex
separable approximations* (2002). At the iterate ``x_k``, each function
``φ`` (the objective, each constraint of the subproblem) is approximated by

    φ̃(x) = r + Σ_j p_j / (u_j - x_j) + q_j / (x_j - l_j)
    p_j = (u_j - x_kj)² (1.001 (∂φ/∂x_j)⁺ + 0.001 (∂φ/∂x_j)⁻ + rho / range_j)
    q_j = (x_kj - l_j)² (0.001 (∂φ/∂x_j)⁺ + 1.001 (∂φ/∂x_j)⁻ + rho / range_j)

with ``r`` such that ``φ̃(x_k) = φ(x_k)``. Since ``1.001 a⁺ + 0.001 a⁻ =
0.501 |a| + 0.5 a``, the constraints need only products with the rows ``G``
and with ``|G|``: their ``p`` and ``q`` are never formed, except for the
small subproblems solved by the interior point.

The approximations are evaluated around the iterate, with ``d = x - x_k``::

    φ̃(x) = φ(x_k) + Σ_j c⁺_j A_j - c⁻_j B_j
    A_j = (u_j - x_kj) d_j / (u_j - x_j),   B_j = (x_kj - l_j) d_j / (x_j - l_j)

where ``c⁺`` and ``c⁻`` are the brackets of ``p`` and ``q``: every term is
proportional to the step, so nothing large cancels out. Computed through
``r``, the approximations would subtract sums of the size of the gradients:
in float32 rows, that left an error of 1e-5 on the optimum.
"""

from dataclasses import dataclass

import numpy as np

from gemseo_lso.core import kernels
from gemseo_lso.core.arrays import Array
from gemseo_lso.core.arrays import Rows
from gemseo_lso.core.arrays import dense
from gemseo_lso.core.arrays import is_sparse
from gemseo_lso.core.arrays import rows_times
from gemseo_lso.core.arrays import times_rows
from gemseo_lso.core.settings import Settings

MMA_RHO = 1e-5
"""The constant curvature term of MMA (Svanberg's ``raa0``)."""

GCMMA_RHO_MIN = 1e-6
"""The smallest curvature term of GCMMA."""


def asymptotes(
    x: Array,
    x_previous: Array | None,
    x_before: Array | None,
    lower_previous: Array | None,
    upper_previous: Array | None,
    ranges: Array,
    settings: Settings,
) -> tuple[Array, Array]:
    """The lower and upper asymptotes at ``x``.

    Args:
        x: The iterate.
        x_previous: The iterate before, if any.
        x_before: The iterate before that, if any.
        lower_previous: The lower asymptotes of the previous iteration.
        upper_previous: The upper asymptotes of the previous iteration.
        ranges: ``upper - lower`` of the variables.
        settings: The settings.

    Returns:
        The asymptotes, between 0.01 and 10 ranges from ``x``.
    """
    if (
        x_previous is None
        or x_before is None
        or lower_previous is None
        or upper_previous is None
    ):
        lower = x - settings.asymptote_init * ranges
        upper = x + settings.asymptote_init * ranges
    else:
        trend = (x - x_previous) * (x_previous - x_before)
        factor = np.where(
            trend < 0,
            settings.asymptote_decrease,
            np.where(trend > 0, settings.asymptote_increase, 1.0),
        )
        lower = x - factor * (x_previous - lower_previous)
        upper = x + factor * (upper_previous - x_previous)
    lower = np.clip(lower, x - 10 * ranges, x - 0.01 * ranges)
    upper = np.clip(upper, x + 0.01 * ranges, x + 10 * ranges)
    return lower, upper


def move_limits(
    x: Array,
    lower_asymptote: Array,
    upper_asymptote: Array,
    lower: Array,
    upper: Array,
    settings: Settings,
) -> tuple[Array, Array]:
    """The bounds of the subproblem.

    Within the bounds of the variables, the move limit, and away from the
    asymptotes.
    """
    ranges = upper - lower
    alpha = np.maximum.reduce(
        [
            lower,
            lower_asymptote + 0.1 * (x - lower_asymptote),
            x - settings.move_limit * ranges,
        ]
    )
    beta = np.minimum.reduce(
        [
            upper,
            upper_asymptote - 0.1 * (upper_asymptote - x),
            x + settings.move_limit * ranges,
        ]
    )
    return alpha, beta


def gcmma_rho(gradients: Rows, ranges: Array) -> Array:
    """The first curvature terms of functions at an outer iteration of GCMMA.

    Args:
        gradients: Their gradients, one per row, dense or sparse.
        ranges: The ranges of the variables.
    """
    sizes = rows_times(abs(gradients), ranges).ravel()
    rho: Array = np.maximum(GCMMA_RHO_MIN, 0.1 * sizes / ranges.size)
    return rho


@dataclass
class Approximation:
    """The approximations of the objective and of the constraints at ``x_k``.

    Args:
        x: The iterate ``x_k``.
        lower_asymptote: ``l``.
        upper_asymptote: ``u``.
        alpha: The lower bounds of the subproblem.
        beta: The upper bounds of the subproblem.
        ranges: ``upper - lower`` of the variables.
        objective: ``f(x_k)``.
        objective_gradient: Its gradient.
        constraints: ``g(x_k)`` of the constraints of the subproblem.
        rows: Their gradients, of shape ``(m, n)``, dense or sparse.
        objective_rho: The curvature term of the objective.
        constraint_rho: Those of the constraints, of shape ``(m,)``.
    """

    x: Array
    lower_asymptote: Array
    upper_asymptote: Array
    alpha: Array
    beta: Array
    ranges: Array
    objective: float
    objective_gradient: Array
    constraints: Array
    rows: Rows
    objective_rho: float
    constraint_rho: Array

    def __post_init__(self) -> None:
        up, low, x = self.upper_asymptote, self.lower_asymptote, self.x
        self._ux2 = (up - x) ** 2
        self._xl2 = (x - low) ** 2
        self._abs_rows = abs(self.rows)
        self._inverse_ranges = 1.0 / self.ranges
        self._zeros = np.zeros(x.size)
        self.set_rho(self.objective_rho, self.constraint_rho)

    @property
    def size(self) -> int:
        """The number of constraints of the subproblem."""
        return int(self.constraints.size)

    def set_rho(self, objective_rho: float, constraint_rho: Array) -> None:
        """Change the curvature terms (the inner iterations of GCMMA)."""
        self.objective_rho = objective_rho
        self.constraint_rho = np.asarray(constraint_rho, dtype=float)
        up, low, x = self.upper_asymptote, self.lower_asymptote, self.x
        gradient = self.objective_gradient
        positive = np.maximum(gradient, 0.0)
        negative = np.maximum(-gradient, 0.0)
        term = objective_rho / self.ranges
        self._p0 = self._ux2 * (1.001 * positive + 0.001 * negative + term)
        self._q0 = self._xl2 * (0.001 * positive + 1.001 * negative + term)
        self._r0 = self.objective - float(
            np.sum(self._p0 / (up - x) + self._q0 / (x - low))
        )

    def aggregated(self, multipliers: Array) -> tuple[Array, Array]:
        """``P`` and ``Q`` of the Lagrangian ``φ̃_0 + Σ λ_i φ̃_i``."""
        if not self.size:
            return self._p0, self._q0
        absolute = times_rows(multipliers, self._abs_rows)
        signed = times_rows(multipliers, self.rows)
        term = float(multipliers @ self.constraint_rho) / self.ranges
        p = self._p0 + self._ux2 * (0.501 * absolute + 0.5 * signed + term)
        q = self._q0 + self._xl2 * (0.501 * absolute - 0.5 * signed + term)
        return p, q

    def minimizer(self, p: Array, q: Array) -> Array:
        """The point of the subproblem bounds minimizing ``Σ P/(u-x) + Q/(x-l)``."""
        root_p, root_q = np.sqrt(p), np.sqrt(q)
        x = (root_p * self.lower_asymptote + root_q * self.upper_asymptote) / (
            root_p + root_q
        )
        clipped: Array = np.clip(x, self.alpha, self.beta)
        return clipped

    def _products(self, multipliers: Array) -> tuple[Array, Array, float]:
        """``λᵀ|G|``, ``λᵀG`` and ``λ·rho``: the products with the rows."""
        if not self.size:
            return self._zeros, self._zeros, 0.0
        # In the precision of the rows: the kernels compute in float64.
        return (
            times_rows(multipliers, self._abs_rows, None),
            times_rows(multipliers, self.rows, None),
            float(multipliers @ self.constraint_rho),
        )

    def _vectors(self) -> tuple[Array, ...]:
        """The vectors the kernels read, in their order."""
        return (
            self.lower_asymptote,
            self.upper_asymptote,
            self.alpha,
            self.beta,
            self._inverse_ranges,
            self._ux2,
            self._xl2,
            self._p0,
            self._q0,
        )

    def curvature(self, multipliers: Array, x: Array) -> tuple[Rows, Array, Array]:
        """The pieces of the Hessian of the dual at ``multipliers``.

        The Jacobian of the approximated constraints at ``x`` is ``S + rho wᵀ``:
        ``S`` has the pattern of the rows, ``rho wᵀ`` comes from the curvature
        terms. The Hessian of the dual is ``-(S + rho wᵀ) D⁻¹ (S + rho wᵀ)ᵀ``
        (minus the elastic terms), ``D`` the curvature of the Lagrangian in
        the variables not at the bounds of the subproblem.

        Args:
            multipliers: The multipliers.
            x: The minimizer of the Lagrangian at them.

        Returns:
            ``S`` (float64, sparse if the rows are), ``D⁻¹`` (zero for the
            variables at a bound of the subproblem) and ``w``.
        """
        absolute, signed, rho = self._products(multipliers)
        size = x.size
        inverse, left, right, w = (np.empty(size) for _ in range(4))
        kernels.curvature(
            x, *self._vectors(), absolute, signed, rho, inverse, left, right, w
        )
        if is_sparse(self.rows):
            shape = self.rows.shape
            rows = self.rows.astype(float).tocsr()
            abs_rows = self._abs_rows.astype(float).tocsr()
            pattern = (
                abs_rows.multiply(left.reshape(1, -1))
                + rows.multiply(right.reshape(1, -1))
            ).tocsr()
            pattern.resize(shape)
        else:
            pattern = dense(self._abs_rows) * left + dense(self.rows) * right
        return pattern, inverse, w

    def _steps(self, x: Array) -> tuple[Array, Array]:
        """``A`` and ``B`` of the approximations around the iterate."""
        step = x - self.x
        a = (self.upper_asymptote - self.x) * step / (self.upper_asymptote - x)
        b = (self.x - self.lower_asymptote) * step / (x - self.lower_asymptote)
        return a, b

    def objective_value(self, x: Array) -> float:
        """``φ̃_0(x)``."""
        a, b = self._steps(x)
        p = self._p0 / self._ux2
        q = self._q0 / self._xl2
        return self.objective + float(np.sum(p * a - q * b))

    def constraint_values(self, x: Array) -> Array:
        """``φ̃_i(x)`` of every constraint of the subproblem."""
        if not self.size:
            return np.zeros(0)
        a, b = self._steps(x)
        values: Array = np.asarray(
            self.constraints
            + 0.501 * rows_times(self._abs_rows, a - b)
            + 0.5 * rows_times(self.rows, a + b)
            + self.constraint_rho * float(np.sum((a - b) / self.ranges)),
            dtype=float,
        )
        return values

    def dual(
        self, multipliers: Array, elastic_cost: Array, elastic_quadratic: float
    ) -> tuple[float, Array, Array, Array]:
        """The dual function of the subproblem and its gradient.

        With the elastic variables ``y_i >= 0`` of cost ``c_i y_i + d y_i²/2``,
        the dual is concave and continuously differentiable.

        Returns:
            The dual value less ``φ(x_k)``, its gradient, the minimizing ``x``
            and ``y``.
        """
        absolute, signed, rho = self._products(multipliers)
        size = self.x.size
        # A - B and A + B only multiply the rows: in their precision.
        steps = self.rows.dtype if self.size else float
        x = np.empty(size)
        difference, total = np.empty(size, steps), np.empty(size, steps)
        objective_change, curvature_change = kernels.primal(
            self.x, *self._vectors(), absolute, signed, rho, x, difference, total
        )
        excess = np.maximum(multipliers - elastic_cost, 0.0)
        y = excess / elastic_quadratic
        constraints = self.constraints
        if self.size:
            constraints = (
                self.constraints
                + 0.501 * rows_times(self._abs_rows, difference)
                + 0.5 * rows_times(self.rows, total)
                + self.constraint_rho * curvature_change
            )
        gradient = constraints - y
        # The Lagrangian at its minimizer: φ̃_0 + λ·(φ̃ - y) + c·y + d y²/2,
        # less the constant φ(x_k): of the order of the number of variables
        # times the largest term of the gradient, it drowned the ascent of the
        # last steps of Newton's method in its rounding.
        value = (
            objective_change
            + float(multipliers @ gradient)
            + float(elastic_cost @ y)
            + 0.5 * elastic_quadratic * float(y @ y)
        )
        return value, gradient, x, y

    def explicit(self) -> tuple[Array, Array, Array, Array, Array, float]:
        """The terms of the approximations, formed in full: small subproblems only.

        Returns:
            ``p``, ``q``, ``r`` of the constraints, then of the objective.
        """
        term = self.constraint_rho[:, None] / self.ranges
        rows, abs_rows = dense(self.rows), dense(self._abs_rows)
        p = self._ux2 * (0.501 * abs_rows + 0.5 * rows + term)
        q = self._xl2 * (0.501 * abs_rows - 0.5 * rows + term)
        up, low = self.upper_asymptote, self.lower_asymptote
        r = self.constraints - p @ (1 / (up - self.x)) - q @ (1 / (self.x - low))
        return p, q, r, self._p0, self._q0, self._r0

    def conservative_weight(self, x: Array) -> float:
        """How much ``φ̃(x)`` grows per unit of ``rho`` (Svanberg's ``w``)."""
        up, low = self.upper_asymptote, self.lower_asymptote
        return float(
            np.sum(
                (up - low) * (x - self.x) ** 2 / ((up - x) * (x - low) * self.ranges)
            )
        )
