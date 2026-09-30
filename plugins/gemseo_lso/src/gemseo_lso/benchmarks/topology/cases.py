"""The classic cases of stress-constrained topology optimization (spec § 9).

The loads grow with the grid and the radii are fractions of it, so that the
stresses and the designs do not depend on the refinement: a grid of ``n``
elements across is a domain of size 1, meshed finer.
"""

import numpy as np

from gemseo_lso.benchmarks.topology.model import StressTopology

FILTER_SHARE = 0.015
"""The radius of the density filter, as a share of the width (1.5 elements at
100)."""

PATTERN_SHARE = 0.06
"""The radius of the pattern of a stress constraint, as a share of the width."""


def _node(column: int, row: int, columns: int) -> int:
    return row * (columns + 1) + column


def l_bracket(size: int, stress_limit: float = 45.0) -> StressTopology:
    """The L-shaped bracket: a square without its upper right 0.6 × 0.6.

    Clamped at the top of its vertical arm, loaded downwards at the tip of its
    horizontal arm, the load spread over 5 % of the width below its upper
    corner. Its reentrant corner concentrates the stress: the relaxed
    constraints round it. About ``0.64 size²`` elements.

    Args:
        size: The elements across.
        stress_limit: ``sigma_lim``, for a total load of ``size``: at 45, the
            optimum has a volume fraction of 0.375, in the range of the
            published designs (0.3 to 0.4); at 30, no design is feasible.
    """
    cut = round(0.4 * size)
    rows, columns = np.mgrid[0:size, 0:size]
    mask = ~((rows >= cut) & (columns >= cut))
    fixed = [
        2 * _node(column, size, size) + direction
        for column in range(cut + 1)
        for direction in (0, 1)
    ]
    spread = max(2, round(0.05 * size))
    nodes = [_node(size, cut - k, size) for k in range(spread + 1)]
    loads = {2 * node + 1: -size / len(nodes) for node in nodes}
    return StressTopology(
        mask=mask,
        fixed=np.asarray(fixed),
        loads=loads,
        stress_limit=stress_limit,
        filter_radius=max(1.5, FILTER_SHARE * size),
        radius=max(3.0, PATTERN_SHARE * size),
        summary=(
            "An L-shaped bracket: a square without its upper right corner. Its "
            "vertical arm is clamped along its top edge; the tip of its "
            "horizontal arm is loaded downwards, near its upper corner."
        ),
        features=(
            {
                "name": "reentrant corner",
                "node": (cut, cut),
                "note": "The inner corner of the L: in linear elasticity the "
                "stress there is singular and grows as the mesh is refined. When "
                "the stress constraints stay violated or costly at the corner "
                "(check the hot spots and the prices), rounding it removes the "
                "singularity: emptying a disk of a few elements around it, so "
                "that the material goes around the corner.",
            },
        ),
    )


def cantilever(columns: int, rows: int, stress_limit: float = 2.0) -> StressTopology:
    """A cantilever beam clamped on its left side, loaded down at its right middle.

    Args:
        columns: The elements along the beam.
        rows: The elements across.
        stress_limit: ``sigma_lim``, for a total load of ``rows``.
    """
    mask = np.ones((rows, columns), dtype=bool)
    fixed = [
        2 * _node(0, row, columns) + direction
        for row in range(rows + 1)
        for direction in (0, 1)
    ]
    middle = rows // 2
    spread = max(1, round(0.1 * rows))
    nodes = [
        _node(columns, row, columns)
        for row in range(max(0, middle - spread), min(rows, middle + spread) + 1)
    ]
    loads = {2 * node + 1: -rows / len(nodes) for node in nodes}
    return StressTopology(
        mask=mask,
        fixed=np.asarray(fixed),
        loads=loads,
        stress_limit=stress_limit,
        filter_radius=max(1.5, FILTER_SHARE * columns),
        radius=max(3.0, PATTERN_SHARE * columns),
        summary=(
            "A cantilever beam clamped along its left edge, loaded downwards "
            "at the middle of its right edge."
        ),
    )
