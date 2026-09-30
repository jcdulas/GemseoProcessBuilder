"""The working set: the constraints whose rows an iteration uses (spec § 3.3).

Only values are needed to choose it: the constraints close to activity, the
active ones of the last subproblem, and, by hysteresis, those of the last
working set still within a wider margin.

Example:
    >>> import numpy as np
    >>> from gemseo_lso.core.settings import Settings
    >>> values = np.array([-2.0, -0.1, 0.3, -0.6])
    >>> working_set(values, 0.3, None, np.zeros(4), Settings())
    array([1, 2])
"""

import numpy as np

from gemseo_lso.core.arrays import Array
from gemseo_lso.core.arrays import Indices
from gemseo_lso.core.settings import Settings

SCREENING_SAFETY = 2.0
"""The margin is this many times the largest change of a constraint over the
last step: what the next step could plausibly change."""

ACTIVE_MULTIPLIER = 1e-6
"""A multiplier above this share of the largest one marks an active constraint."""


def screening_margin(
    constraints: Array, previous: Array | None, settings: Settings
) -> float:
    """The distance to activity under which a constraint is in the working set.

    Twice the largest change of a constraint over the last step, between
    ``screening_margin_min`` and ``screening_margin``: wide while the
    iterates move, narrow as they converge.
    """
    if previous is None or not constraints.size:
        return settings.screening_margin
    change = float(np.max(np.abs(constraints - previous)))
    return float(
        np.clip(
            SCREENING_SAFETY * change,
            settings.screening_margin_min,
            settings.screening_margin,
        )
    )


def working_set(
    constraints: Array,
    margin: float,
    previous: Indices | None,
    multipliers: Array,
    settings: Settings,
) -> Indices:
    """The indices of the constraints of the working set, sorted.

    Args:
        constraints: The values of all the inequality constraints.
        margin: The screening margin.
        previous: The last working set, if any.
        multipliers: The multipliers of the last subproblem, one per constraint.
        settings: The settings.

    Returns:
        The constraints active in the last subproblem, whatever their number,
        and the others up to ``max_working_set`` indices, the largest values
        kept. Capping an active constraint would drop its multiplier: the
        subproblem would ignore it, a repair would add it back at every
        iteration, and the KKT residual would miss its term.
    """
    selected = constraints >= -margin
    active = np.zeros(constraints.size, dtype=bool)
    if multipliers.size:
        largest = float(multipliers.max())
        active = multipliers > ACTIVE_MULTIPLIER * max(1.0, largest)
        selected |= active
    if previous is not None and previous.size:
        kept = previous[constraints[previous] >= -settings.keep_factor * margin]
        selected[kept] = True
    indices = np.flatnonzero(selected)
    if indices.size > settings.max_working_set:
        others = indices[~active[indices]]
        room = max(settings.max_working_set - int(np.count_nonzero(active)), 0)
        order = np.argsort(-constraints[others], kind="stable")
        indices = np.sort(
            np.concatenate([np.flatnonzero(active), others[order[:room]]])
        )
    return indices
