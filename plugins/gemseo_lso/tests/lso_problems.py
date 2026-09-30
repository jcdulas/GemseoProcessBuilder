"""Test problems with known optima."""

from dataclasses import dataclass

import numpy as np

from gemseo_lso.core import DenseProblem
from gemseo_lso.core.arrays import Array


@dataclass(frozen=True)
class Known:
    """A problem and its optimum."""

    name: str
    problem: DenseProblem
    x: Array
    objective: float


def cantilever() -> Known:
    """Svanberg's cantilever beam (1987): five segments, one compliance constraint."""
    c = np.array([61.0, 37.0, 19.0, 7.0, 1.0])
    return Known(
        "cantilever",
        DenseProblem(
            x0=np.full(5, 5.0),
            lower=np.full(5, 1.0),
            upper=np.full(5, 10.0),
            objective=lambda x: float(0.0624 * x.sum()),
            objective_gradient=lambda x: np.full(5, 0.0624),
            constraints=lambda x: np.array([np.sum(c / x**3) - 1.0]),
            constraint_jacobian=lambda x: (-3 * c / x**4)[None, :],
        ),
        np.array([6.016, 5.309, 4.494, 3.502, 2.153]),
        1.340,
    )


def two_spheres() -> Known:
    """Svanberg's toy problem: the smallest point in the intersection of two balls."""
    centers = np.array([[5.0, 2.0, 1.0], [3.0, 4.0, 3.0]])
    return Known(
        "two_spheres",
        DenseProblem(
            x0=np.array([4.0, 3.0, 2.0]),
            lower=np.zeros(3),
            upper=np.full(3, 5.0),
            objective=lambda x: float(x @ x),
            objective_gradient=lambda x: 2 * x,
            constraints=lambda x: np.sum((x - centers) ** 2, axis=1) - 9.0,
            constraint_jacobian=lambda x: 2 * (x - centers),
        ),
        np.array([2.0175, 1.7800, 1.2375]),
        8.770246,
    )


def hs21() -> Known:
    """Hock-Schittkowski 21."""
    return Known(
        "hs21",
        DenseProblem(
            x0=np.array([-1.0, -1.0]),
            lower=np.array([2.0, -50.0]),
            upper=np.array([50.0, 50.0]),
            objective=lambda x: float(0.01 * x[0] ** 2 + x[1] ** 2 - 100),
            objective_gradient=lambda x: np.array([0.02 * x[0], 2 * x[1]]),
            constraints=lambda x: np.array([10.0 - 10 * x[0] + x[1]]),
            constraint_jacobian=lambda x: np.array([[-10.0, 1.0]]),
        ),
        np.array([2.0, 0.0]),
        -99.96,
    )


def hs35() -> Known:
    """Hock-Schittkowski 35."""

    def objective(x: Array) -> float:
        a, b, c = x
        return float(
            9
            - 8 * a
            - 6 * b
            - 4 * c
            + 2 * a**2
            + 2 * b**2
            + c**2
            + 2 * a * b
            + 2 * a * c
        )

    def gradient(x: Array) -> Array:
        a, b, c = x
        return np.array(
            [-8 + 4 * a + 2 * b + 2 * c, -6 + 4 * b + 2 * a, -4 + 2 * c + 2 * a]
        )

    return Known(
        "hs35",
        DenseProblem(
            x0=np.full(3, 0.5),
            lower=np.zeros(3),
            upper=np.full(3, 3.0),
            objective=objective,
            objective_gradient=gradient,
            constraints=lambda x: np.array([x[0] + x[1] + 2 * x[2] - 3]),
            constraint_jacobian=lambda x: np.array([[1.0, 1.0, 2.0]]),
        ),
        np.array([4 / 3, 7 / 9, 4 / 9]),
        1 / 9,
    )


def hs43() -> Known:
    """Hock-Schittkowski 43 (Rosen-Suzuki), with bounds added."""

    def objective(x: Array) -> float:
        a, b, c, d = x
        return float(a**2 + b**2 + 2 * c**2 + d**2 - 5 * a - 5 * b - 21 * c + 7 * d)

    def gradient(x: Array) -> Array:
        a, b, c, d = x
        return np.array([2 * a - 5, 2 * b - 5, 4 * c - 21, 2 * d + 7])

    def constraints(x: Array) -> Array:
        a, b, c, d = x
        return np.array(
            [
                a**2 + b**2 + c**2 + d**2 + a - b + c - d - 8,
                a**2 + 2 * b**2 + c**2 + 2 * d**2 - a - d - 10,
                2 * a**2 + b**2 + c**2 + 2 * a - b - d - 5,
            ]
        )

    def jacobian(x: Array) -> Array:
        a, b, c, d = x
        return np.array(
            [
                [2 * a + 1, 2 * b - 1, 2 * c + 1, 2 * d - 1],
                [2 * a - 1, 4 * b, 2 * c, 4 * d - 1],
                [4 * a + 2, 2 * b - 1, 2 * c, -1.0],
            ]
        )

    return Known(
        "hs43",
        DenseProblem(
            x0=np.zeros(4),
            lower=np.full(4, -10.0),
            upper=np.full(4, 10.0),
            objective=objective,
            objective_gradient=gradient,
            constraints=constraints,
            constraint_jacobian=jacobian,
        ),
        np.array([0.0, 1.0, 2.0, -1.0]),
        -44.0,
    )


def hs76() -> Known:
    """Hock-Schittkowski 76, with upper bounds added."""

    def objective(x: Array) -> float:
        a, b, c, d = x
        return float(
            a**2 + 0.5 * b**2 + c**2 + 0.5 * d**2 - a * c + c * d - a - 3 * b + c - d
        )

    def gradient(x: Array) -> Array:
        a, b, c, d = x
        return np.array([2 * a - c - 1, b - 3, 2 * c - a + d + 1, d + c - 1])

    matrix = np.array(
        [[1.0, 2.0, 1.0, 1.0], [3.0, 1.0, 2.0, -1.0], [0.0, -1.0, -4.0, 0.0]]
    )
    rhs = np.array([5.0, 4.0, -1.5])
    return Known(
        "hs76",
        DenseProblem(
            x0=np.full(4, 0.5),
            lower=np.zeros(4),
            upper=np.full(4, 5.0),
            objective=objective,
            objective_gradient=gradient,
            constraints=lambda x: matrix @ x - rhs,
            constraint_jacobian=lambda x: matrix,
        ),
        np.array([0.2727273, 2.090909, 0.0, 0.5454545]),
        -4.681818,
    )


def rosenbrock() -> Known:
    """Rosenbrock in a disk of radius 1.2 (the constraint is active)."""

    def objective(x: Array) -> float:
        return float((1 - x[0]) ** 2 + 100 * (x[1] - x[0] ** 2) ** 2)

    def gradient(x: Array) -> Array:
        return np.array(
            [
                -2 * (1 - x[0]) - 400 * x[0] * (x[1] - x[0] ** 2),
                200 * (x[1] - x[0] ** 2),
            ]
        )

    return Known(
        "rosenbrock",
        DenseProblem(
            x0=np.array([-1.0, 1.0]),
            lower=np.full(2, -2.0),
            upper=np.full(2, 2.0),
            objective=objective,
            objective_gradient=gradient,
            constraints=lambda x: np.array([x @ x - 1.2**2 / 2]),
            constraint_jacobian=lambda x: 2 * x[None, :],
        ),
        np.array([np.nan, np.nan]),  # Computed by SLSQP in the tests.
        np.nan,
    )


PROBLEMS = (cantilever, two_spheres, hs21, hs35, hs43, hs76)
