"""The solvers of the MMA subproblem (spec § 3.7).

The subproblem, with the elastic variables ``y`` of Svanberg's standard form::

    minimize    φ̃_0(x) + Σ_i c_i y_i + d y_i² / 2
    subject to  φ̃_i(x) - y_i <= 0,   alpha <= x <= beta,   y >= 0

is convex and separable. Three solvers:

- ``solve_dual``: its dual, maximized over ``λ >= 0`` by L-BFGS-B; one dual
  evaluation costs four products with the rows, for any number of
  constraints;
- ``solve_newton``: its dual, maximized by a projected Newton method whose
  Hessian is factorized: sparse when the rows are, 10 to 20 steps instead of
  hundreds of L-BFGS-B evaluations;
- ``solve_interior_point``: a primal-dual interior-point method on the
  perturbed KKT conditions, reduced to a dense system of the size of the
  number of constraints: accurate, for small subproblems.
"""

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from scipy.linalg import lu_factor
from scipy.linalg import lu_solve
from scipy.linalg import solve
from scipy.optimize import Bounds
from scipy.optimize import minimize
from scipy.sparse.linalg import splu

from gemseo_lso.core.approximation import Approximation
from gemseo_lso.core.arrays import Array
from gemseo_lso.core.arrays import Indices
from gemseo_lso.core.arrays import is_sparse

BARRIER_MIN = 1e-9
"""The last barrier parameter of the interior point."""


@dataclass(frozen=True)
class SubproblemSolution:
    """The solution of a subproblem."""

    x: Array
    multipliers: Array
    """``λ``, one per constraint of the subproblem."""

    elastic: Array
    """``y``, positive where a constraint could not be met."""

    converged: bool = True
    """Whether the solver reached its tolerance (the interior point may not)."""


def solve_dual(
    approximation: Approximation,
    elastic_cost: float,
    elastic_quadratic: float,
    start: Array,
    tolerance: float = 1e-5,
) -> SubproblemSolution:
    """Solve the subproblem by maximizing its dual with L-BFGS-B.

    Args:
        approximation: The approximations at the iterate.
        elastic_cost: ``c``.
        elastic_quadratic: ``d``.
        start: The multipliers to start from.
        tolerance: The largest projected gradient of the dual at its solution:
            the violation of the approximated constraints left.
    """
    size = approximation.size
    if not size:
        p, q = approximation.aggregated(np.zeros(0))
        x = approximation.minimizer(p, q)
        return SubproblemSolution(x, np.zeros(0), np.zeros(0))
    cost = np.full(size, elastic_cost)

    def negative_dual(multipliers: Array) -> tuple[float, Array]:
        value, gradient, _, _ = approximation.dual(multipliers, cost, elastic_quadratic)
        return -value, -gradient

    origin = np.zeros(size)
    point = np.maximum(start, 0.0)
    for attempt in range(RESTARTS + 1):
        result = minimize(
            negative_dual,
            point,
            jac=True,
            method="L-BFGS-B",
            bounds=Bounds(origin, np.full(size, np.inf)),
            options={
                "maxiter": 100_000,
                "maxfun": 200_000,
                "ftol": 0.0,
                "gtol": tolerance,
                "maxcor": LBFGS_MEMORY,
            },
        )
        multipliers = np.maximum(result.x, 0.0)
        if (
            result.success
            or _projected_gradient_norm(multipliers, -result.jac) <= tolerance
        ):
            break
        # Stopped without converging (a failed line search, on an ill-conditioned
        # dual): again from there, its memory emptied, then from the origin.
        point = multipliers if attempt == 0 else origin
    multipliers = np.maximum(result.x, 0.0)
    _, _, x, y = approximation.dual(multipliers, cost, elastic_quadratic)
    return SubproblemSolution(x, multipliers, y)


RESTARTS = 2
"""The times L-BFGS-B is started again on a dual it left unsolved. On Svanberg's
beam with 10⁴ segments, it ended with a line search failure ("ABNORMAL") in 6
of 15 subproblems, its projected gradient 40 times the tolerance and up to
10¹⁶: MMA then took the wrong steps for seven iterations, and did not converge
in 300 with the interior point in the same case."""

LBFGS_MEMORY = 100
"""The pairs L-BFGS-B keeps (10 by default): the duals of nearly infeasible
subproblems are ill-conditioned; with 100, a restoration of the bracket took
half the evaluations. Its cost per iteration, proportional to the number of
constraints, is small next to an evaluation of the dual."""

NEWTON_MAX_ITERATIONS = 30
"""Newton steps per subproblem, at most. Near the optimum the dual is smooth
and Newton converges in 3 to 5 steps; far from it (a start violating many
constraints), the dual is made of many pieces and an exact solution took up
to 226 steps for nothing: the next outer iteration corrects an inexact
subproblem, and the step is checked against all the constraints anyway. At
10⁵ variables and constraints, a run took 13.6 s without the cap, 5.5 s with
20 steps, for the same iterations and solution."""

DAMPING_MIN = 1e-10
DAMPING_MAX = 1.0
"""The range of the Levenberg-Marquardt damping, relative to the largest
diagonal term of the Hessian of the dual."""
ARMIJO = 1e-4
"""The share of the first-order increase a Newton step must achieve."""


def _projected_gradient_norm(multipliers: Array, gradient: Array) -> float:
    """The largest component of the projected gradient of the dual."""
    return float(
        np.max(np.abs(_projected_gradient(multipliers, gradient)), initial=0.0)
    )


def _projected_gradient(multipliers: Array, gradient: Array) -> Array:
    """The gradient of the dual, with the components blocked at ``λ = 0`` zeroed."""
    projected: Array = np.where(multipliers > 0, gradient, np.maximum(gradient, 0.0))
    return projected


def solve_newton(
    approximation: Approximation,
    elastic_cost: float,
    elastic_quadratic: float,
    start: Array,
    tolerance: float = 1e-5,
) -> SubproblemSolution:
    """Solve the subproblem by a projected Newton method on its dual.

    The Hessian of the dual is ``-(S + rho wᵀ) D⁻¹ (S + rho wᵀ)ᵀ`` minus the
    elastic terms (``Approximation.curvature``). With sparse rows, ``S D⁻¹ Sᵀ``
    is sparse — a constraint is coupled only to those sharing variables with
    it — and is factorized by a sparse LU; the rank-two terms of ``rho`` are
    added by the Woodbury formula. The multipliers at 0 whose gradient pushes
    them below stay there (Bertsekas' projected Newton); the others take the
    Newton step, shortened by an Armijo search along the projected path.

    Args:
        approximation: The approximations at the iterate.
        elastic_cost: ``c``.
        elastic_quadratic: ``d``.
        start: The multipliers to start from.
        tolerance: The largest projected gradient of the dual at its solution.
    """
    size = approximation.size
    if not size:
        return solve_dual(approximation, elastic_cost, elastic_quadratic, start)
    cost = np.full(size, elastic_cost)
    multipliers = np.maximum(start, 0.0)
    value, gradient, x, _ = approximation.dual(multipliers, cost, elastic_quadratic)
    damping = DAMPING_MIN
    for _ in range(NEWTON_MAX_ITERATIONS):
        projected = _projected_gradient(multipliers, gradient)
        if float(np.max(np.abs(projected))) <= tolerance:
            break
        blocked = (multipliers <= 0) & (gradient <= 0)
        free = np.flatnonzero(~blocked)
        direction = np.zeros(size)
        direction[free] = _newton_direction(
            approximation,
            multipliers,
            x,
            gradient,
            free,
            cost,
            elastic_quadratic,
            damping,
        )
        if float(gradient @ direction) <= 0:
            direction = projected  # Not an ascent direction: the gradient then.
        step = 1.0
        halvings = 0
        for _ in range(40):
            trial = np.maximum(multipliers + step * direction, 0.0)
            trial_value, trial_gradient, trial_x, _ = approximation.dual(
                trial, cost, elastic_quadratic
            )
            if trial_value >= value + ARMIJO * float(gradient @ (trial - multipliers)):
                break
            step /= 2
            halvings += 1
        else:
            break  # No ascent left: at the precision of the dual.
        # Levenberg-Marquardt: the dual is piecewise smooth (variables reaching
        # the bounds of the subproblem, multipliers reaching the elastic cost),
        # and a Newton step across pieces overshoots: damp after a shortened
        # step, undamp after a full one.
        if halvings > 1:
            damping = min(DAMPING_MAX, damping * 10)
        elif halvings == 0:
            damping = max(DAMPING_MIN, damping / 10)
        multipliers, value, gradient, x = trial, trial_value, trial_gradient, trial_x
    _, _, x, y = approximation.dual(multipliers, cost, elastic_quadratic)
    return SubproblemSolution(x, multipliers, y)


def _newton_direction(
    approximation: Approximation,
    multipliers: Array,
    x: Array,
    gradient: Array,
    free: Indices,
    cost: Array,
    elastic_quadratic: float,
    damping: float,
) -> Array:
    """The Newton step of the free multipliers: ``N⁻¹ g`` with ``N = -Hessian``.

    ``damping`` times the largest diagonal term is added to the diagonal.
    """
    pattern, inverse, w = approximation.curvature(multipliers, x)
    rho = approximation.constraint_rho[free]
    if is_sparse(pattern):
        rows = pattern.tocsr()[free]
        product = (rows.multiply(inverse.reshape(1, -1)) @ rows.T).tocsc()
        v = np.asarray(rows @ (inverse * w)).ravel()
    else:
        rows = pattern[free]
        product = (rows * inverse) @ rows.T
        v = rows @ (inverse * w)
    elastic = np.where(multipliers[free] > cost[free], 1.0 / elastic_quadratic, 0.0)
    diagonal = np.asarray(product.diagonal()).ravel() + elastic
    shift = damping * max(float(diagonal.max(initial=0.0)), 1e-300) + 1e-300
    if is_sparse(product):
        system = (product + sparse.diags(elastic + shift)).tocsc()
        factor = splu(system)
        solve_system = factor.solve
    else:
        system = product + np.diag(elastic + shift)
        factor = lu_factor(system)

        def solve_system(right: Array) -> Array:
            solved: Array = lu_solve(factor, right)
            return solved

    g = gradient[free]
    # Woodbury: N = K + U C Uᵀ, U = [rho, v], C = [[wᵀD⁻¹w, 1], [1, 0]].
    k_g = np.asarray(solve_system(g), dtype=float)
    if not rho.any():
        return k_g
    u = np.column_stack([rho, v])
    k_u = np.column_stack([solve_system(u[:, 0]), solve_system(u[:, 1])])
    s = float(w @ (inverse * w))
    c_inverse = np.array([[0.0, 1.0], [1.0, -s]])
    small = c_inverse + u.T @ k_u
    try:
        correction = k_u @ np.linalg.solve(small, u.T @ k_g)
    except np.linalg.LinAlgError:
        return k_g
    direction: Array = k_g - correction
    return direction


def checked(
    approximation: Approximation,
    solution: SubproblemSolution,
    elastic_cost: float,
    elastic_quadratic: float,
    tolerance: float,
) -> SubproblemSolution:
    """The solution of the interior point, solved again by the dual if it failed.

    The interior point may not converge, silently: on Svanberg's beam with 10⁴
    segments it returned the same point, at 45 above the optimum of a merit of
    44, for eight different subproblems, its Newton iterations exhausted at a
    barrier stage. The dual solver, started from its multipliers, takes over.

    Args:
        approximation: The approximations at the iterate.
        solution: What the interior point returned.
        elastic_cost: ``c``.
        elastic_quadratic: ``d``.
        tolerance: The tolerance of the dual of the run.
    """
    if solution.converged:
        return solution
    return solve_dual(
        approximation, elastic_cost, elastic_quadratic, solution.multipliers, tolerance
    )


def solve_scaled(matrix: Array, right: Array) -> Array:
    """Solve a symmetric positive definite system, equilibrated by its diagonal.

    The diagonal of the reduced system of the interior point spans twenty
    orders of magnitude at the end of the barrier (the terms ``s / λ``): its
    condition number, 10²⁰ and more, made LAPACK warn of an inaccurate result
    on the truss problems of the literature. Scaled to a unit diagonal, the
    same system is well conditioned.

    Args:
        matrix: The matrix.
        right: The right-hand side.
    """
    scale = 1.0 / np.sqrt(np.maximum(np.diag(matrix), 1e-300))
    scaled = matrix * scale[:, None] * scale[None, :]
    solution: Array = scale * solve(scaled, scale * right, assume_a="pos")
    return solution


def solve_interior_point(
    approximation: Approximation, elastic_cost: float, elastic_quadratic: float
) -> SubproblemSolution:
    """Solve the subproblem by a primal-dual interior-point method.

    The perturbed KKT conditions, with the bound multipliers ``ξ``, ``η``, the
    elastic multipliers ``μ`` and the slacks ``s``::

        ∇φ̃_0 + Jᵀλ - ξ + η = 0          c + d y - λ - μ = 0
        φ̃(x) - y + s = 0                 ξ (x - alpha) = ε,  η (beta - x) = ε
        μ y = ε,  λ s = ε

    Newton's steps are reduced to a system in ``λ``, of the size of the
    number of constraints; ``ε`` decreases from 1 to ``BARRIER_MIN``.
    """
    p, q, r, p0, q0, _ = approximation.explicit()
    lower, upper = approximation.lower_asymptote, approximation.upper_asymptote
    alpha, beta = approximation.alpha, approximation.beta
    size = approximation.size
    c = np.full(size, elastic_cost)
    d = elastic_quadratic

    x = 0.5 * (alpha + beta)
    y = np.ones(size)
    lam = np.ones(size)
    s = np.ones(size)
    xsi = np.maximum(1.0, 1.0 / (x - alpha))
    eta = np.maximum(1.0, 1.0 / (beta - x))
    mu = np.maximum(1.0, 0.5 * c)

    def residuals(
        x: Array,
        y: Array,
        lam: Array,
        s: Array,
        xsi: Array,
        eta: Array,
        mu: Array,
        epsilon: float,
    ) -> list[Array]:
        ux, xl = 1.0 / (upper - x), 1.0 / (x - lower)
        big_p, big_q = p0 + lam @ p, q0 + lam @ q
        return [
            big_p * ux**2 - big_q * xl**2 - xsi + eta,
            c + d * y - lam - mu,
            r + p @ ux + q @ xl - y + s,
            xsi * (x - alpha) - epsilon,
            eta * (beta - x) - epsilon,
            mu * y - epsilon,
            lam * s - epsilon,
        ]

    def norm(parts: list[Array]) -> float:
        return float(np.sqrt(sum(float(part @ part) for part in parts)))

    epsilon = 1.0
    converged = True
    while True:
        for _ in range(200):
            parts = residuals(x, y, lam, s, xsi, eta, mu, epsilon)
            if (
                max(float(np.abs(part).max(initial=0.0)) for part in parts)
                < 0.9 * epsilon
            ):
                break
            rx, ry, rl, rxsi, reta, rmu, rs = parts
            ux, xl = 1.0 / (upper - x), 1.0 / (x - lower)
            big_p, big_q = p0 + lam @ p, q0 + lam @ q
            hessian = 2 * big_p * ux**3 + 2 * big_q * xl**3
            jacobian = p * ux**2 - q * xl**2
            dx_diag = hessian + xsi / (x - alpha) + eta / (beta - x)
            rtx = rx + rxsi / (x - alpha) - reta / (beta - x)
            dy_diag = d + mu / y
            rty = ry + rmu / y
            dl_diag = 1.0 / dy_diag + s / lam
            rtl = rl + rty / dy_diag - rs / lam
            schur = (jacobian / dx_diag) @ jacobian.T + np.diag(dl_diag)
            dlam = solve_scaled(schur, rtl - jacobian @ (rtx / dx_diag))
            dx = -(rtx + jacobian.T @ dlam) / dx_diag
            dy = (dlam - rty) / dy_diag
            dxsi = (-rxsi - xsi * dx) / (x - alpha)
            deta = (-reta + eta * dx) / (beta - x)
            dmu = (-rmu - mu * dy) / y
            ds = (-rs - s * dlam) / lam
            # The longest step keeping every positive quantity positive.
            ratios = [
                -1.01 * dx / (x - alpha),
                1.01 * dx / (beta - x),
                *(
                    -1.01 * step / value
                    for step, value in (
                        (dy, y),
                        (dlam, lam),
                        (ds, s),
                        (dxsi, xsi),
                        (deta, eta),
                        (dmu, mu),
                    )
                ),
            ]
            step = 1.0 / max(1.0, *(float(ratio.max(initial=0.0)) for ratio in ratios))
            before = norm(parts)
            for _ in range(50):
                trial = (
                    x + step * dx,
                    y + step * dy,
                    lam + step * dlam,
                    s + step * ds,
                    xsi + step * dxsi,
                    eta + step * deta,
                    mu + step * dmu,
                )
                if norm(residuals(*trial, epsilon)) < before:
                    break
                step /= 2
            x, y, lam, s, xsi, eta, mu = trial
        else:
            converged = False  # The stage ended on its 200 iterations.
        if epsilon <= BARRIER_MIN:
            break
        epsilon *= 0.1
    # The barrier leaves a variable at epsilon / ξ from its bound: 2.5e-6 for
    # the gradients of 4e-4 of an objective on a scale of 1, not at the bound
    # for the KKT residual. On a bound where its multiplier exceeds the gap.
    x = np.where(xsi > x - alpha, alpha, np.where(eta > beta - x, beta, x))
    return SubproblemSolution(np.clip(x, alpha, beta), lam, y, converged)
