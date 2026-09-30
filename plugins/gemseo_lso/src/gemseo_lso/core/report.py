"""What the optimizer tells after each iteration, and at the end (spec § 5)."""

from dataclasses import dataclass

from gemseo_lso.core.arrays import Array
from gemseo_lso.core.state import Status


@dataclass(frozen=True)
class Report:
    """An outer iteration."""

    iteration: int
    """The index of the new iterate."""

    objective: float
    max_constraint: float
    violated: int
    """Constraints above ``ineq_tolerance``."""

    active: int
    """Constraints within ``ineq_tolerance`` of their bound, or above."""

    working_set: int
    """Constraints of the subproblem."""

    rows_computed: int
    rows_reused: int
    screening_repairs: int
    inner_iterations: int
    """GCMMA: the subproblems solved again before the step was conservative."""

    kkt_residual: float
    """At the previous iterate, with the multipliers of its subproblem."""

    step: float
    """The largest move of a variable, relative to its range."""

    asymptote_spread: tuple[float, float, float]
    """The smallest, median and largest ``(u - l) / range``."""

    model_time: float
    """Seconds spent in the problem (values and gradients)."""

    optimizer_time: float
    """Seconds spent in the optimizer itself."""

    method: str
    """The method of the iteration: ``gcmma`` once MMA has switched to it."""

    status: Status
    directional_derivatives: int = 0
    """``hybrid``: the directional derivatives of a new colored Jacobian
    (none between two colorings); ``rows_computed`` counts the exact rows."""

    restoration: int = 0
    """The iterations spent restoring feasibility, this one included (0: none)."""

    descent: int = 0
    """The iterations spent in the descent through the constraints, this one
    included (0: not descending)."""

    at_bound: int = 0
    """The variables at one of their bounds."""

    near_bound: int = 0
    """The variables at, or within 1 % of their range from, one of their bounds."""

    bound_costs: tuple[tuple[int, float, float], ...] = ()
    """The variables at or near a bound whose exit costs the least: their index,
    the change of the Lagrangian if they moved toward the bound (relative to
    the KKT scale: for a variable at it, the cost of leaving it) and their
    distance from it, as a share of their range; cheapest first. A small or
    negative cost is a bound that may not hold: a decision, often taken early,
    that the optimizer could not question."""


@dataclass(frozen=True)
class Result:
    """The end of a run."""

    x: Array
    objective: float
    max_constraint: float
    iterations: int
    evaluations: int
    row_evaluations: int
    status: Status
    message: str
    directional_derivatives: int = 0
    """``hybrid``: the directional derivatives asked for."""
