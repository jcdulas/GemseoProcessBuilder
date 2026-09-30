"""A large problem with a known solution: local constraints, few of them active.

Minimize ``||x - t||² / 2`` subject to ``A x - b <= 0`` and ``0 <= x <= 1``,
where each constraint involves three neighbouring variables. The solution
``x*`` is drawn inside the bounds, a share of the constraints is made active
at it (``b_i = a_i x*``) with positive multipliers ``λ*``, the others are
satisfied with a slack, and ``t = x* + Aᵀ λ*`` makes ``(x*, λ*)`` a KKT point:
the problem is convex, so ``x*`` is its only solution.

For the colored Jacobians (spec § 3.9), it gives its pattern (the three
variables of each constraint, on a ring or on a 2D grid) and a tangent mode;
an optional far coupling adds to every constraint a small term on the
variables around it, decaying with the distance, outside the pattern: its
Jacobian is then sparse only approximately, like a mechanical constraint
coupled to the whole structure through its state.

Example:
    >>> problem = LocalConstraints(size=100, active_share=0.05, seed=1)
    >>> problem.lower.size, problem.jacobian.shape
    (100, (100, 100))
"""

import numpy as np
from numpy.typing import NDArray
from scipy import sparse

from gemseo_lso.core.arrays import Array
from gemseo_lso.core.arrays import Indices
from gemseo_lso.core.arrays import Rows

WIDTH = 3
"""Variables per constraint."""

REACH = 8
"""The far coupling reaches this many variables on each side."""


class LocalConstraints:
    """The problem, one constraint per variable, its rows sparse.

    Args:
        size: The number of variables and of constraints.
        active_share: The share of constraints active at the solution.
        slack: The range of the slacks of the inactive constraints.
        seed: The seed of the random draws.
        grid: Whether the variables are the cells of a square grid (``size`` a
            square), each constraint on a cell and its right and lower
            neighbours; else on a ring, on three consecutive variables.
        coupling: The weight of the far coupling (0: none).
        tangent: Whether to give directional derivatives (else the colored
            Jacobians use finite differences).
    """

    def __init__(
        self,
        size: int,
        active_share: float = 0.02,
        slack: tuple[float, float] = (0.05, 2.0),
        seed: int = 0,
        grid: bool = False,
        coupling: float = 0.0,
        tangent: bool = True,
    ) -> None:
        rng = np.random.default_rng(seed)
        columns = _columns(size, grid)
        values = rng.standard_normal((size, WIDTH))
        values /= np.linalg.norm(values, axis=1, keepdims=True)
        rows = np.repeat(np.arange(size), WIDTH)
        self.pattern = sparse.csr_matrix(
            (np.ones(rows.size, dtype=bool), (rows, columns.ravel())),
            shape=(size, size),
        )
        """The pattern given to the optimizer: without the far coupling."""

        self.jacobian = sparse.csr_matrix(
            (values.ravel(), (rows, columns.ravel())), shape=(size, size)
        )
        if coupling:
            self.jacobian = sparse.csr_matrix(self.jacobian + _coupling(size, coupling))
        self.tangent = tangent
        self.products = 0
        """The directional derivatives given."""

        self.solution: Array = rng.uniform(0.2, 0.8, size)
        active = rng.random(size) < active_share
        self.active: Indices = np.flatnonzero(active)
        slacks = np.where(active, 0.0, rng.uniform(*slack, size))
        self._bound = self.jacobian @ self.solution + slacks
        self.multipliers: Array = np.where(active, rng.uniform(0.5, 2.0, size), 0.0)
        self._target: Array = np.asarray(
            self.solution + self.jacobian.T @ self.multipliers, dtype=float
        )
        self.optimum = float(0.5 * np.sum((self.solution - self._target) ** 2))
        self._x0 = np.full(size, 0.5)
        self._lower = np.zeros(size)
        self._upper = np.ones(size)
        self.evaluations = 0
        self.rows = 0
        """The rows given."""

    @property
    def x0(self) -> Array:
        """The middle of the bounds."""
        return self._x0

    @property
    def lower(self) -> Array:
        """0."""
        return self._lower

    @property
    def upper(self) -> Array:
        """1."""
        return self._upper

    def values(self, x: Array) -> tuple[float, Array, Array]:
        """The objective and the constraints; no equality."""
        self.evaluations += 1
        objective = float(0.5 * np.sum((x - self._target) ** 2))
        return objective, self.jacobian @ x - self._bound, np.zeros(0)

    def objective_gradient(self, x: Array) -> Array:
        """``x - t``."""
        return x - self._target

    def constraint_rows(self, x: Array, rows: Indices) -> Rows:
        """Rows of ``A``, sparse."""
        self.rows += len(rows)
        return self.jacobian[rows]

    def equality_rows(self, x: Array) -> Array:
        """No equality constraint."""
        return np.zeros((0, self._x0.size))

    def sparsity(self) -> sparse.csr_matrix:
        """The pattern, without the far coupling."""
        return self.pattern

    def directional_derivatives(
        self, x: Array, directions: sparse.csc_matrix
    ) -> Array | None:
        """``A @ directions``, counted; ``None`` without a tangent mode."""
        if not self.tangent:
            return None
        self.products += directions.shape[1]
        return np.asarray((self.jacobian @ directions).toarray())


def _columns(size: int, grid: bool) -> NDArray[np.intp]:
    """The variables of each constraint."""
    index = np.arange(size)
    if not grid:
        return (index[:, None] + np.arange(WIDTH)) % size
    side = int(np.sqrt(size))
    if side * side != size:
        msg = f"A grid needs a square number of variables, not {size}."
        raise ValueError(msg)
    row, column = divmod(index, side)
    right = row * side + (column + 1) % side
    below = ((row + 1) % side) * side + column
    return np.stack([index, right, below], axis=1)


def _coupling(size: int, weight: float) -> sparse.csr_matrix:
    """A term on the variables around each constraint, decaying with distance."""
    offsets = np.arange(-REACH, REACH + 1)
    decay = weight * np.exp(-np.abs(offsets) / (REACH / 3))
    rows = np.repeat(np.arange(size), offsets.size)
    columns = (rows + np.tile(offsets + 1, size)) % size
    return sparse.csr_matrix(
        (np.tile(decay, size), (rows, columns)), shape=(size, size)
    )
