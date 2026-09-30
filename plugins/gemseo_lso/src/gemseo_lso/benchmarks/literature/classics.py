"""Classic test problems, with their published optima.

- Svanberg's cantilever beam (1987) with any number of segments, whose optimum
  is known in closed form: the problem MMA was made for, one constraint and as
  many variables as wanted;
- three problems of Hock and Schittkowski (1981), the collection every
  nonlinear programming code is tried on: numbers 71 (an equality constraint),
  100 and 113, with the optimal values of the book.

Example:
    >>> problem, x_star, f_star = beam(5)
    >>> round(f_star, 3)
    1.34
"""

import numpy as np

from gemseo_lso.core.arrays import Array
from gemseo_lso.core.problem import DenseProblem

WEIGHT = 0.0624
"""The weight of a segment of unit size."""


def beam(
    segments: int, spread: float | None = None
) -> tuple[DenseProblem, Array, float]:
    """Svanberg's cantilever beam: minimize the weight for a given tip deflection.

    ``minimize 0.0624 Σ x_j`` under ``Σ c_j / x_j³ <= 1`` with ``c_j = 3 j² -
    3 j + 1``, the segments counted from the tip (1, 7, 19, 37, 61 for five).
    The Lagrange conditions give the optimum for any number of segments::

        x_j = c_j^(1/4) (Σ_k c_k^(1/4))^(1/3),   f = 0.0624 (Σ_k c_k^(1/4))^(4/3)

    For five segments, 1.340 and (2.153, 3.502, 4.494, 5.309, 6.016) from the tip.

    The optimal sizes grow as ``j^(1/2)``: they span two orders of magnitude at
    10⁴ segments, four at 10⁵. With the same bounds for all (the default), the
    smallest are far from their upper bound, and MMA, which measures its moves
    and its asymptotes against the range of a variable, moves them slowly.

    Args:
        segments: The number of segments.
        spread: When given, the bounds of each segment are its optimal size
            divided and multiplied by it; the same bounds for all otherwise.

    Returns:
        The problem, its optimum and the optimal weight. The variables are the
        sizes between their bounds, scaled to [0, 1]; without ``spread``, the
        upper bound is ten times the largest optimal size, the lower one 1.
    """
    j = np.arange(1, segments + 1, dtype=float)
    c = 3 * j**2 - 3 * j + 1
    root: Array = c**0.25
    x_star: Array = root * root.sum() ** (1 / 3)
    f_star = float(WEIGHT * root.sum() ** (4 / 3))
    high: Array
    low: Array
    if spread is None:
        high = np.full(segments, float(10 * x_star.max()))
        low = np.ones(segments)
    else:
        high, low = spread * x_star, x_star / spread
    width: Array = high - low

    def size(y: Array) -> Array:
        sizes: Array = low + width * np.asarray(y, dtype=float)
        return sizes

    problem = DenseProblem(
        x0=np.full(segments, 0.5),
        lower=np.zeros(segments),
        upper=np.ones(segments),
        objective=lambda y: float(WEIGHT * size(y).sum()),
        objective_gradient=lambda y: WEIGHT * width,
        constraints=lambda y: np.array([np.sum(c / size(y) ** 3) - 1.0]),
        constraint_jacobian=lambda y: (-3 * c * width / size(y) ** 4)[None, :],
    )
    return problem, (x_star - low) / width, f_star


def hs71() -> tuple[DenseProblem, Array, float]:
    """Hock-Schittkowski 71: an inequality and an equality constraint.

    ``min x1 x4 (x1 + x2 + x3) + x3`` under ``x1 x2 x3 x4 >= 25``,
    ``Σ x² = 40``, ``1 <= x <= 5``; optimum 17.0140173.
    """

    def objective(x: Array) -> float:
        return float(x[0] * x[3] * (x[0] + x[1] + x[2]) + x[2])

    def gradient(x: Array) -> Array:
        return np.array(
            [
                x[3] * (2 * x[0] + x[1] + x[2]),
                x[0] * x[3],
                x[0] * x[3] + 1.0,
                x[0] * (x[0] + x[1] + x[2]),
            ]
        )

    def inequality(x: Array) -> Array:
        return np.array([25.0 - np.prod(x)])

    def inequality_jacobian(x: Array) -> Array:
        return -(np.prod(x) / x)[None, :]

    problem = DenseProblem(
        x0=np.array([1.0, 5.0, 5.0, 1.0]),
        lower=np.ones(4),
        upper=np.full(4, 5.0),
        objective=objective,
        objective_gradient=gradient,
        constraints=inequality,
        constraint_jacobian=inequality_jacobian,
        equalities=lambda x: np.array([x @ x - 40.0]),
        equality_jacobian=lambda x: 2 * x[None, :],
    )
    x_star = np.array([1.0, 4.742999, 3.821150, 1.379408])
    return problem, x_star, 17.0140173


def hs100() -> tuple[DenseProblem, Array, float]:
    """Hock-Schittkowski 100: seven variables, four nonlinear constraints.

    Optimum 680.6300573; the variables are bounded in [-10, 10] here.
    """

    def objective(x: Array) -> float:
        return float(
            (x[0] - 10) ** 2
            + 5 * (x[1] - 12) ** 2
            + x[2] ** 4
            + 3 * (x[3] - 11) ** 2
            + 10 * x[4] ** 6
            + 7 * x[5] ** 2
            + x[6] ** 4
            - 4 * x[5] * x[6]
            - 10 * x[5]
            - 8 * x[6]
        )

    def gradient(x: Array) -> Array:
        return np.array(
            [
                2 * (x[0] - 10),
                10 * (x[1] - 12),
                4 * x[2] ** 3,
                6 * (x[3] - 11),
                60 * x[4] ** 5,
                14 * x[5] - 4 * x[6] - 10,
                4 * x[6] ** 3 - 4 * x[5] - 8,
            ]
        )

    def constraints(x: Array) -> Array:
        return -np.array(
            [
                127 - 2 * x[0] ** 2 - 3 * x[1] ** 4 - x[2] - 4 * x[3] ** 2 - 5 * x[4],
                282 - 7 * x[0] - 3 * x[1] - 10 * x[2] ** 2 - x[3] + x[4],
                196 - 23 * x[0] - x[1] ** 2 - 6 * x[5] ** 2 + 8 * x[6],
                -4 * x[0] ** 2 - x[1] ** 2 + 3 * x[0] * x[1] - 2 * x[2] ** 2
                - 5 * x[5] + 11 * x[6],
            ]
        )  # fmt: skip

    def jacobian(x: Array) -> Array:
        rows = np.zeros((4, 7))
        rows[0, [0, 1, 2, 3, 4]] = [-4 * x[0], -12 * x[1] ** 3, -1, -8 * x[3], -5]
        rows[1, [0, 1, 2, 3, 4]] = [-7, -3, -20 * x[2], -1, 1]
        rows[2, [0, 1, 5, 6]] = [-23, -2 * x[1], -12 * x[5], 8]
        rows[3, [0, 1, 2, 5, 6]] = [
            -8 * x[0] + 3 * x[1],
            -2 * x[1] + 3 * x[0],
            -4 * x[2],
            -5,
            11,
        ]
        return -rows

    problem = DenseProblem(
        x0=np.array([1.0, 2.0, 0.0, 4.0, 0.0, 1.0, 1.0]),
        lower=np.full(7, -10.0),
        upper=np.full(7, 10.0),
        objective=objective,
        objective_gradient=gradient,
        constraints=constraints,
        constraint_jacobian=jacobian,
    )
    x_star = np.array(
        [2.330499, 1.951372, -0.4775414, 4.365726, -0.6244870, 1.038131, 1.594227]
    )
    return problem, x_star, 680.6300573


def hs113() -> tuple[DenseProblem, Array, float]:
    """Hock-Schittkowski 113: ten variables, eight nonlinear constraints.

    Optimum 24.3062091; the variables are bounded in [-10, 20] here.
    """

    def objective(x: Array) -> float:
        return float(
            x[0] ** 2 + x[1] ** 2 + x[0] * x[1] - 14 * x[0] - 16 * x[1]
            + (x[2] - 10) ** 2 + 4 * (x[3] - 5) ** 2 + (x[4] - 3) ** 2
            + 2 * (x[5] - 1) ** 2 + 5 * x[6] ** 2 + 7 * (x[7] - 11) ** 2
            + 2 * (x[8] - 10) ** 2 + (x[9] - 7) ** 2 + 45
        )  # fmt: skip

    def gradient(x: Array) -> Array:
        return np.array(
            [
                2 * x[0] + x[1] - 14,
                2 * x[1] + x[0] - 16,
                2 * (x[2] - 10),
                8 * (x[3] - 5),
                2 * (x[4] - 3),
                4 * (x[5] - 1),
                10 * x[6],
                14 * (x[7] - 11),
                4 * (x[8] - 10),
                2 * (x[9] - 7),
            ]
        )

    def values(x: Array) -> Array:
        x1, x2, x3, x4, x5, x6, x7, x8, x9, x10 = x
        return np.array(
            [
                105 - 4 * x1 - 5 * x2 + 3 * x7 - 9 * x8,
                -10 * x1 + 8 * x2 + 17 * x7 - 2 * x8,
                8 * x1 - 2 * x2 - 5 * x9 + 2 * x10 + 12,
                -3 * (x1 - 2) ** 2 - 4 * (x2 - 3) ** 2 - 2 * x3**2 + 7 * x4 + 120,
                -5 * x1**2 - 8 * x2 - (x3 - 6) ** 2 + 2 * x4 + 40,
                -(x1**2) - 2 * (x2 - 2) ** 2 + 2 * x1 * x2 - 14 * x5 + 6 * x6,
                -0.5 * (x1 - 8) ** 2 - 2 * (x2 - 4) ** 2 - 3 * x5**2 + x6 + 30,
                3 * x1 - 6 * x2 - 12 * (x9 - 8) ** 2 + 7 * x10,
            ]
        )

    def jacobian(x: Array) -> Array:
        rows = np.zeros((8, 10))
        rows[0, [0, 1, 6, 7]] = [-4, -5, 3, -9]
        rows[1, [0, 1, 6, 7]] = [-10, 8, 17, -2]
        rows[2, [0, 1, 8, 9]] = [8, -2, -5, 2]
        rows[3, [0, 1, 2, 3]] = [-6 * (x[0] - 2), -8 * (x[1] - 3), -4 * x[2], 7]
        rows[4, [0, 1, 2, 3]] = [-10 * x[0], -8, -2 * (x[2] - 6), 2]
        rows[5, [0, 1, 4, 5]] = [
            -2 * x[0] + 2 * x[1],
            -4 * (x[1] - 2) + 2 * x[0],
            -14,
            6,
        ]
        rows[6, [0, 1, 4, 5]] = [-(x[0] - 8), -4 * (x[1] - 4), -6 * x[4], 1]
        rows[7, [0, 1, 8, 9]] = [3, -6, -24 * (x[8] - 8), 7]
        return -rows

    problem = DenseProblem(
        x0=np.array([2.0, 3.0, 5.0, 5.0, 1.0, 2.0, 7.0, 3.0, 6.0, 10.0]),
        lower=np.full(10, -10.0),
        upper=np.full(10, 20.0),
        objective=objective,
        objective_gradient=gradient,
        constraints=lambda x: -values(x),
        constraint_jacobian=jacobian,
    )
    x_star = np.array(
        [2.171996, 2.363683, 8.773926, 5.095984, 0.9906548, 1.430574, 1.321644,
         9.828726, 8.280092, 8.375927]
    )  # fmt: skip
    return problem, x_star, 24.3062091
