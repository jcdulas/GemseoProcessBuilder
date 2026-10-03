"""Relaxing some inequality constraints, then bringing them back (spec § 3.10).

A constraint ``g_i <= 0`` relaxed by ``r_i`` becomes ``g_i <= r_i``. The state
keeps the *effective* values ``g_i - r_i``: everything the optimizer decides
from them (the screening, the subproblem, the feasibility, the restoration,
the KKT residual) is that of the relaxed problem, with no other change. The
offsets are saved with the state, so that a run resumed from it goes on with the
same relaxation. The optimizer reads the true values back, ``g_i = effective +
r_i``, for what concerns the original problem: the best feasible point, the
reports and the result.

Tightening the offsets step by step (``tighten_state``) brings the constraints
back to the original problem: a continuation from a design that the constraints
held back to one that satisfies them.
"""

import numpy as np

from gemseo_lso.core.arrays import Array
from gemseo_lso.core.arrays import Indices
from gemseo_lso.core.state import State


def relax_state(state: State, indices: Indices, amount: float) -> None:
    """Relax some inequality constraints to ``g <= amount``.

    Args:
        state: The state, changed in place.
        indices: The constraints, among all the inequality constraints.
        amount: The offset, in the units of the constraints (``g`` standardized
            as ``g <= 0``); 0 brings these constraints back.
    """
    if amount < 0:
        msg = f"A constraint is relaxed by a positive amount, not {amount}."
        raise ValueError(msg)
    indices = np.asarray(indices, dtype=int)
    if indices.size and (indices.min() < 0 or indices.max() >= state.constraints.size):
        msg = f"The constraints are numbered 0 to {state.constraints.size - 1}."
        raise ValueError(msg)
    old = _offsets(state)
    new = old.copy()
    new[indices] = amount
    _shift(state, old, new)


def tighten_state(state: State, factor: float, tolerance: float = 0.0) -> None:
    """Multiply the offsets by ``factor``; those below ``tolerance`` vanish.

    Args:
        state: The state, changed in place.
        factor: In ``[0, 1]``: 0 brings every constraint back at once.
        tolerance: The offsets under it are dropped (the constraint is the
            original one again).
    """
    if not 0 <= factor <= 1:
        msg = f"The factor of a tightening is in [0, 1], not {factor}."
        raise ValueError(msg)
    old = _offsets(state)
    new = old * factor
    new[new <= tolerance] = 0.0
    _shift(state, old, new)


def true_constraints(state: State) -> Array:
    """The constraints of the original problem at the iterate."""
    if state.relaxation is None:
        return state.constraints
    return state.constraints + state.relaxation


def _offsets(state: State) -> Array:
    if state.relaxation is None:
        return np.zeros(state.constraints.size)
    return state.relaxation


def _shift(state: State, old: Array, new: Array) -> None:
    """Make the effective values those of the new offsets, without evaluation."""
    change = old - new
    state.constraints = state.constraints + change
    if state.constraints_previous is not None:
        state.constraints_previous = state.constraints_previous + change
    state.relaxation = new if new.any() else None
