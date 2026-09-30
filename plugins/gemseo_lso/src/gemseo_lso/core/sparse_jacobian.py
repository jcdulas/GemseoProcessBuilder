"""The Jacobian of the constraints from directional derivatives (spec § 3.9).

One directional derivative per color, in the direction of the sum of its
variables — by the tangent mode of the model, or by forward finite differences
on the values — and each entry of the pattern read in the product of its
variable's color, once per coloring. Every coloring is valid on the pattern,
so each reading is the entry itself plus what the entries outside the pattern
leak into it: the least-squares estimate over the colorings is the mean of the
readings, and their spread estimates the leakage.

Between two colorings, Schubert's sparse update corrects the Jacobian from the
change of the constraint values over the step, with no evaluation.

Example:
    >>> import numpy as np
    >>> from gemseo_lso.benchmarks.synthetic import LocalConstraints
    >>> from gemseo_lso.core.coloring import color
    >>> problem = LocalConstraints(60, seed=1)
    >>> coloring = color(problem.sparsity(), margin=1, overlap=2)
    >>> jacobian, directions, evaluations = colored_jacobian(
    ...     problem.directional_derivatives, None, problem.x0, None, coloring,
    ...     problem.lower, problem.upper, 1e-6)
    >>> bool(abs(jacobian.matrix - problem.jacobian).max() < 1e-12), evaluations
    (True, 0)
"""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field

import numpy as np
from scipy import sparse

from gemseo_lso.core.arrays import Array
from gemseo_lso.core.arrays import Indices
from gemseo_lso.core.arrays import dense
from gemseo_lso.core.coloring import Coloring
from gemseo_lso.core.coloring import check_pattern
from gemseo_lso.core.coloring import color
from gemseo_lso.core.problem import LargeScaleProblem
from gemseo_lso.core.settings import Settings

Derivatives = Callable[[Array, sparse.csc_matrix], Array | None]
"""The directional derivatives of the constraints, ``None`` without a tangent mode."""

Values = Callable[[Array], Array]
"""The values of the inequality constraints."""


@dataclass
class ColoredJacobian:
    """The Jacobian of the inequality constraints on the pattern."""

    matrix: sparse.csr_matrix
    """The entries of the pattern, float64."""

    leakage: Array
    """For each constraint, the estimated error of its row relative to its norm
    (the spread of its readings over the colorings; zero with one coloring)."""

    computed_at: int = 0
    """The iteration of the last coloring."""

    _rows: Indices = field(init=False, repr=False)
    """The row of each entry."""

    def __post_init__(self) -> None:
        self._rows = np.repeat(
            np.arange(self.matrix.shape[0]), np.diff(self.matrix.indptr)
        )

    def rows(self, indices: Indices) -> sparse.csr_matrix:
        """The rows of some constraints."""
        return sparse.csr_matrix(self.matrix[indices])

    def update(self, step: Array, change: Array) -> None:
        """Schubert's update: each row made exact along the step, on its pattern.

        Args:
            step: The step ``x_(k+1) - x_k``.
            change: ``g(x_(k+1)) - g(x_k)``.
        """
        matrix = self.matrix
        components = step[matrix.indices]
        size = matrix.shape[0]
        norms = np.bincount(self._rows, weights=components**2, minlength=size)
        residual = change - matrix @ step
        factor = np.divide(residual, norms, out=np.zeros(size), where=norms > 0)
        matrix.data += factor[self._rows] * components


def recover(
    coloring: Coloring, products: Array, scale: Array
) -> tuple[sparse.csr_matrix, Array]:
    """The entries of the pattern from the directional derivatives.

    Args:
        coloring: The colorings.
        products: The products of the Jacobian with the directions, of shape
            ``(constraints, total)``.
        scale: The component of each variable in its directions.

    Returns:
        The Jacobian on the pattern, and the estimated leakage of each row.
    """
    pattern = coloring.pattern
    size = pattern.shape[0]
    rows = np.repeat(np.arange(size), np.diff(pattern.indptr))
    columns = pattern.indices
    readings = (
        np.stack(
            [
                products[rows, offset + colors[columns]]
                for offset, colors in zip(
                    coloring.offsets, coloring.colors, strict=True
                )
            ]
        )
        / scale[columns]
    )
    entries = readings.mean(axis=0)
    spread = readings.std(axis=0)
    norms = np.sqrt(np.bincount(rows, weights=entries**2, minlength=size))
    spreads = np.sqrt(np.bincount(rows, weights=spread**2, minlength=size))
    leakage = np.divide(
        spreads,
        norms,
        out=np.where(spreads > 0, np.inf, 0.0),
        where=norms > 0,
    )
    matrix = sparse.csr_matrix(
        (entries, pattern.indices.copy(), pattern.indptr.copy()), shape=pattern.shape
    )
    return matrix, leakage


def colored_jacobian(
    derivatives: Derivatives | None,
    values: Values | None,
    x: Array,
    constraints: Array | None,
    coloring: Coloring,
    lower: Array,
    upper: Array,
    difference_step: float,
) -> tuple[ColoredJacobian, int, int]:
    """The Jacobian at ``x`` from one directional derivative per color.

    Args:
        derivatives: The tangent mode of the model, if any.
        values: The values of the constraints, for finite differences.
        x: The point.
        constraints: The values at ``x``, for finite differences.
        coloring: The colorings.
        lower: The lower bounds: a step never leaves the bounds.
        upper: The upper bounds.
        difference_step: The step of the finite differences, relative to the
            ranges.

    Returns:
        The Jacobian, the number of directional derivatives and the number of
        evaluations of the values (finite differences).
    """
    if derivatives is not None:
        products = derivatives(x, coloring.directions(np.ones(x.size)))
        if products is not None:
            ones = np.ones(x.size)
            matrix, leakage = recover(coloring, np.asarray(products, dtype=float), ones)
            return ColoredJacobian(matrix, leakage), coloring.total, 0
    if values is None or constraints is None:
        msg = "Finite differences need the values of the constraints."
        raise ValueError(msg)
    step = difference_step * (upper - lower)
    # Backwards where a step forwards would leave the bounds.
    scale = np.where(x + step > upper, -step, step)
    directions = coloring.directions(scale)
    products = np.empty((constraints.size, coloring.total))
    for index in range(coloring.total):
        direction = directions[:, [index]].toarray().ravel()
        products[:, index] = values(x + direction) - constraints
    matrix, leakage = recover(coloring, products, scale)
    return ColoredJacobian(matrix, leakage), coloring.total, coloring.total


@dataclass(frozen=True)
class SparsityProbe:
    """How far a problem is from its pattern, on a few constraints."""

    rows: Indices
    """The constraints probed."""

    outside: Array
    """For each one, the norm of its exact row outside the pattern, relative
    to the norm of the row."""

    error: Array
    """The error of its colored entries, relative to the norm of the row."""

    leakage: Array
    """The error estimated by the colorings (``ColoredJacobian.leakage``)."""

    colors: int
    """The directional derivatives of a colored Jacobian."""


def probe_sparsity(
    problem: LargeScaleProblem,
    x: Array,
    rows: Indices,
    settings: Settings | None = None,
) -> SparsityProbe:
    """Compare a few exact rows with the colored Jacobian at the same point.

    To choose between ``colored`` and ``hybrid``, and the margin: the share of
    the rows outside the pattern and the error of the colored entries, against
    the error the colorings estimate.

    Args:
        problem: A problem giving a pattern (``sparsity``).
        x: The point.
        rows: The constraints to probe, a few: their exact rows are computed.
        settings: ``pattern_margin``, ``color_overlap`` and ``difference_step``.
    """
    settings = settings or Settings()
    _, constraints, _ = problem.values(x)
    sparsity = getattr(problem, "sparsity", None)
    given = sparsity() if sparsity is not None else None
    if given is None:
        msg = "The problem gives no sparsity pattern."
        raise ValueError(msg)
    pattern = check_pattern(given, (constraints.size, x.size))
    coloring = color(pattern, settings.pattern_margin, settings.color_overlap)
    jacobian, _, _ = colored_jacobian(
        getattr(problem, "directional_derivatives", None),
        lambda point: problem.values(point)[1],
        x,
        constraints,
        coloring,
        problem.lower,
        problem.upper,
        settings.difference_step,
    )
    exact = dense(problem.constraint_rows(x, rows))
    inside = pattern[rows].toarray()
    norms = np.linalg.norm(exact, axis=1)
    norms = np.where(norms > 0, norms, 1.0)
    colored = jacobian.rows(rows).toarray()
    return SparsityProbe(
        rows=rows,
        outside=np.linalg.norm(np.where(inside, 0.0, exact), axis=1) / norms,
        error=np.linalg.norm(np.where(inside, colored - exact, 0.0), axis=1) / norms,
        leakage=jacobian.leakage[rows],
        colors=coloring.total,
    )
