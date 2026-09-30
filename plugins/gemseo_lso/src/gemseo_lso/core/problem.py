"""The problems the optimizer solves (spec § 3.1, § 5).

The optimizer sees a problem through a small protocol: the values of the
objective and of all the constraints at a point, the gradient of the
objective, and the gradients of some constraints (rows of the Jacobian),
asked for in one batch.

Two methods are optional, for the colored Jacobians (spec § 3.9), used only
when ``jacobian_mode`` asks for them: ``sparsity()``, the pattern of the
inequality constraints (a ``scipy.sparse`` boolean matrix of shape
``(m, n)``), and ``directional_derivatives(x, directions)``, the products of
their Jacobian with a batch of directions (a sparse matrix of shape
``(n, k)``), of shape ``(m, k)`` — the tangent mode of the model; without it,
finite differences on the values. Either may be absent or return ``None``.

Example:
    >>> import numpy as np
    >>> problem = DenseProblem(
    ...     x0=np.array([1.0]),
    ...     lower=np.array([0.0]),
    ...     upper=np.array([2.0]),
    ...     objective=lambda x: float(x[0] ** 2),
    ...     objective_gradient=lambda x: 2 * x,
    ...     constraints=lambda x: np.array([0.5 - x[0]]),
    ...     constraint_jacobian=lambda x: np.array([[-1.0]]),
    ... )
    >>> problem.constraint_rows(problem.x0, np.array([0]))
    array([[-1.]])
"""

from collections.abc import Callable
from typing import Protocol

import numpy as np
from scipy import sparse

from gemseo_lso.core.arrays import Array
from gemseo_lso.core.arrays import Indices
from gemseo_lso.core.arrays import Rows


class LargeScaleProblem(Protocol):
    """A problem ``min f(x)`` s.t. ``g(x) <= 0``, ``h(x) = 0``, within bounds."""

    @property
    def x0(self) -> Array:
        """The starting point, within the bounds."""

    @property
    def lower(self) -> Array:
        """The lower bounds of the variables, finite."""

    @property
    def upper(self) -> Array:
        """The upper bounds of the variables, finite."""

    def values(self, x: Array) -> tuple[float, Array, Array]:
        """The objective, all the inequality and all the equality constraints."""

    def objective_gradient(self, x: Array) -> Array:
        """The gradient of the objective, of shape ``(n,)``."""

    def constraint_rows(self, x: Array, rows: Indices) -> Rows:
        """The gradients of some inequality constraints, dense or sparse.

        Of shape ``(len(rows), n)``.

        All the rows of an iteration are asked for at once, so that the model
        can compute them in parallel.
        """

    def equality_rows(self, x: Array) -> Array:
        """The gradients of all the equality constraints, of shape ``(p, n)``."""


class DenseProblem:
    """A problem given by Python functions, its Jacobian computed in full.

    It counts the evaluations and the rows it gives, for the tests.

    Args:
        x0: The starting point.
        lower: The lower bounds.
        upper: The upper bounds.
        objective: The objective.
        objective_gradient: Its gradient.
        constraints: The inequality constraints ``g(x) <= 0``, as a vector.
        constraint_jacobian: Their Jacobian, of shape ``(m, n)``.
        equalities: The equality constraints ``h(x) = 0``, if any.
        equality_jacobian: Their Jacobian, of shape ``(p, n)``.
        sparse_rows: Whether to give the rows as a ``scipy.sparse`` matrix.
        pattern: The sparsity pattern of the inequality constraints, if any
            (colored Jacobians by finite differences: no tangent mode).
    """

    def __init__(
        self,
        x0: Array,
        lower: Array,
        upper: Array,
        objective: Callable[[Array], float],
        objective_gradient: Callable[[Array], Array],
        constraints: Callable[[Array], Array],
        constraint_jacobian: Callable[[Array], Array],
        equalities: Callable[[Array], Array] | None = None,
        equality_jacobian: Callable[[Array], Array] | None = None,
        sparse_rows: bool = False,
        pattern: sparse.sparray | sparse.spmatrix | None = None,
    ) -> None:
        self._x0 = np.asarray(x0, dtype=float)
        self._lower = np.asarray(lower, dtype=float)
        self._upper = np.asarray(upper, dtype=float)
        self._objective = objective
        self._objective_gradient = objective_gradient
        self._constraints = constraints
        self._constraint_jacobian = constraint_jacobian
        self._equalities = equalities
        self._equality_jacobian = equality_jacobian
        self._sparse_rows = sparse_rows
        self._pattern = pattern
        self.evaluations = 0
        self.rows = 0
        """The number of constraint gradients given."""

        self.requests: list[int] = []
        """The number of rows of each request."""

    @property
    def x0(self) -> Array:
        """The starting point."""
        return self._x0

    @property
    def lower(self) -> Array:
        """The lower bounds."""
        return self._lower

    @property
    def upper(self) -> Array:
        """The upper bounds."""
        return self._upper

    def values(self, x: Array) -> tuple[float, Array, Array]:
        """The objective, the inequality and the equality constraints."""
        self.evaluations += 1
        g = np.atleast_1d(np.asarray(self._constraints(x), dtype=float))
        h = np.zeros(0)
        if self._equalities is not None:
            h = np.atleast_1d(np.asarray(self._equalities(x), dtype=float))
        return float(self._objective(x)), g, h

    def objective_gradient(self, x: Array) -> Array:
        """The gradient of the objective."""
        return np.asarray(self._objective_gradient(x), dtype=float)

    def constraint_rows(self, x: Array, rows: Indices) -> Rows:
        """Some rows of the full Jacobian, counted."""
        self.rows += len(rows)
        self.requests.append(len(rows))
        jacobian = np.atleast_2d(np.asarray(self._constraint_jacobian(x), dtype=float))
        if self._sparse_rows:
            return sparse.csr_matrix(jacobian[rows])
        return jacobian[rows]

    def sparsity(self) -> sparse.sparray | sparse.spmatrix | None:
        """The pattern given, if any."""
        return self._pattern

    def equality_rows(self, x: Array) -> Array:
        """The Jacobian of the equality constraints."""
        if self._equality_jacobian is None:
            return np.zeros((0, self._x0.size))
        return np.atleast_2d(np.asarray(self._equality_jacobian(x), dtype=float))
