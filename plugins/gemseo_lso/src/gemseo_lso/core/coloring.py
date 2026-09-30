"""Colorings of the columns of a sparsity pattern (spec § 3.9).

Variables that never share a constraint can be perturbed together: one
directional derivative in the direction of their sum gives the entries of all
of them (Curtis, Powell and Reid, 1974). A coloring groups the variables so;
the number of colors depends on the size of a neighbourhood, not on the size of
the problem.

The first coloring is made on the pattern widened ``pattern_margin`` times on
itself, so that the variables of a color are farther apart than the nominal
zone of influence of a constraint. ``color_overlap`` colorings measure each
entry several times, each one on the pattern widened once more than the one
before: other companions at other distances. Colorings of the same widened
pattern, even in other orders, come out nearly periodic on a regular stencil
and leak the same far entries: their spread missed the error (correlated
negatively with it over the rows); with a widening more each, it follows it,
at the price of more colors (on a 2D grid, 16 and 51 instead of 16 and 23).

Example:
    >>> import numpy as np
    >>> from scipy import sparse
    >>> ring = sparse.csr_matrix(
    ...     (np.ones(12, dtype=bool), (np.repeat(np.arange(6), 2),
    ...      (np.arange(6)[:, None] + [0, 1]).ravel() % 6)), shape=(6, 6))
    >>> coloring = color(ring, margin=0, overlap=1)
    >>> coloring.counts
    (2,)
    >>> is_valid(ring, coloring.colors[0])
    True
"""

from dataclasses import dataclass

import numpy as np
from scipy import sparse

from gemseo_lso.core import kernels
from gemseo_lso.core.arrays import Array
from gemseo_lso.core.kernels import IntArray


class PatternError(ValueError):
    """A sparsity pattern the optimizer cannot use; the message says why."""


def check_pattern(pattern: object, shape: tuple[int, int]) -> sparse.csr_matrix:
    """A pattern as a boolean CSR matrix, checked.

    Args:
        pattern: The pattern given by the problem.
        shape: The number of inequality constraints and of variables.

    Raises:
        PatternError: When it is not sparse, of another shape, or has an empty
            row (a constraint depending on no variable).
    """
    if not sparse.issparse(pattern):
        msg = (
            "The sparsity pattern must be a scipy.sparse matrix: a dense boolean "
            "matrix takes 10 GB at 10^5 constraints and variables."
        )
        raise PatternError(msg)
    matrix = sparse.csr_matrix(pattern, dtype=bool)
    matrix.eliminate_zeros()
    if matrix.shape != shape:
        msg = (
            f"The sparsity pattern has the shape {matrix.shape}, not {shape} "
            "(constraints, variables)."
        )
        raise PatternError(msg)
    empty = np.flatnonzero(np.diff(matrix.indptr) == 0)
    if empty.size:
        msg = (
            f"{empty.size} constraints depend on no variable in the sparsity "
            f"pattern, the first one {empty[0]}."
        )
        raise PatternError(msg)
    return matrix


def widen(pattern: sparse.csr_matrix, times: int) -> sparse.csr_matrix:
    """The pattern widened on itself, with no coordinates.

    One widening adds to each constraint the variables of the constraints
    sharing a variable with it.
    """
    widened = pattern
    for _ in range(times):
        widened = _widen_once(widened, pattern)
    return widened


def conflicts(pattern: sparse.csr_matrix) -> sparse.csr_matrix:
    """The columns sharing a row of the pattern: the graph to color."""
    as_int = pattern.astype(np.int32)
    return sparse.csr_matrix(as_int.T @ as_int)


def orders(graph: sparse.csr_matrix, count: int) -> list[IntArray]:
    """``count`` orders of the columns, largest degree first.

    The first one breaks the ties by index; the others at random (seeded): on a
    regular stencil, every degree is the same and the orders differ entirely.
    """
    degree = np.diff(graph.indptr)
    result = [np.argsort(-degree, kind="stable").astype(np.int64)]
    for seed in range(1, count):
        ties = np.random.default_rng(seed).permutation(degree.size)
        result.append(np.lexsort((ties, -degree)).astype(np.int64))
    return result


def is_valid(pattern: sparse.csr_matrix, colors: IntArray) -> bool:
    """Whether no two columns of a color share a row of the pattern."""
    rows = np.repeat(np.arange(pattern.shape[0]), np.diff(pattern.indptr))
    keys = (
        rows.astype(np.int64) * (int(colors.max(initial=0)) + 1)
        + colors[pattern.indices]
    )
    return bool(np.unique(keys).size == keys.size)


@dataclass(frozen=True)
class Coloring:
    """The colorings of the columns of a pattern."""

    pattern: sparse.csr_matrix
    """The pattern the entries are recovered on (not widened)."""

    margins: tuple[int, ...]
    """The widenings of the pattern each coloring is valid on."""

    colors: tuple[IntArray, ...]
    """The color of each column, for each coloring."""

    counts: tuple[int, ...]
    """The number of colors of each coloring."""

    @property
    def total(self) -> int:
        """The directional derivatives of a Jacobian: all the colors."""
        return sum(self.counts)

    @property
    def offsets(self) -> IntArray:
        """The first direction of each coloring."""
        return np.concatenate([[0], np.cumsum(self.counts)[:-1]]).astype(np.int64)

    def directions(self, scale: Array) -> sparse.csc_matrix:
        """One direction per color, of shape ``(variables, total)``.

        Args:
            scale: The component of each variable in the direction of its color:
                1 for a tangent mode, the step for finite differences.
        """
        size = scale.size
        rows = np.tile(np.arange(size), len(self.colors))
        columns = np.concatenate(
            [
                offset + colors
                for offset, colors in zip(self.offsets, self.colors, strict=True)
            ]
        )
        values = np.tile(scale, len(self.colors))
        return sparse.csc_matrix((values, (rows, columns)), shape=(size, self.total))


def color(pattern: sparse.csr_matrix, margin: int, overlap: int) -> Coloring:
    """The colorings of a pattern.

    Args:
        pattern: The checked pattern (``check_pattern``).
        margin: The widenings of the pattern before the first coloring.
        overlap: The number of colorings, each on the pattern widened once
            more than the one before.
    """
    widened = widen(pattern, margin)
    colors, counts = [], []
    for index in range(overlap):
        if index:
            widened = _widen_once(widened, pattern)
        graph = conflicts(widened)
        colored, count = kernels.greedy(
            graph.indptr, graph.indices, orders(graph, index + 1)[index]
        )
        colors.append(colored)
        counts.append(count)
    return Coloring(
        pattern=pattern,
        margins=tuple(margin + index for index in range(overlap)),
        colors=tuple(colors),
        counts=tuple(counts),
    )


def _widen_once(
    widened: sparse.csr_matrix, pattern: sparse.csr_matrix
) -> sparse.csr_matrix:
    """``widen(pattern, k + 1)`` from ``widened = widen(pattern, k)``."""
    as_int = pattern.astype(np.int32)
    return sparse.csr_matrix(
        ((widened.astype(np.int32) @ as_int.T) @ as_int).astype(bool)
    )
