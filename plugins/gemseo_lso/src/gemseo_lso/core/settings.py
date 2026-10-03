"""The settings of the optimizer (spec § 4).

Frozen: a new ``Settings`` replaces the old one between two iterations, with
``dataclasses.replace``; nothing is restarted.

Example:
    >>> from dataclasses import replace
    >>> settings = Settings(method="gcmma")
    >>> replace(settings, move_limit=0.2).move_limit
    0.2
"""

from dataclasses import dataclass
from dataclasses import fields
from typing import Literal

Method = Literal["mma", "gcmma"]
DualSolver = Literal["auto", "newton", "lbfgsb", "interior_point"]
RowRefresh = Literal["always", "near_active"]
RowDtype = Literal["float32", "float64"]
JacobianMode = Literal["rows", "hybrid"]


class SettingsError(ValueError):
    """Settings out of their range; the message names the setting."""


@dataclass(frozen=True)
class Settings:
    """How the optimizer runs."""

    method: Method = "mma"
    """MMA, or GCMMA (conservative inner iterations, globally convergent). MMA
    switches to GCMMA by itself when it cycles: its KKT residual not
    decreasing over ``kkt_stall_iterations`` iterations while the iterates
    still move."""

    max_iter: int = 1000
    """Outer iterations, at most."""

    kkt_tolerance: float = 1e-3
    """Stationarity and complementarity, relative to the size of the gradient."""

    ineq_tolerance: float = 1e-5
    """A constraint is satisfied when ``g <= ineq_tolerance``."""

    ftol_rel: float = 0.0
    """Stop when the objective changes less than this, relatively, over
    ``stall_iterations`` iterations (0: never)."""

    xtol_rel: float = 0.0
    """Stop when the point moves less than this, relatively to the ranges, over
    ``stall_iterations`` iterations (0: never)."""

    stall_iterations: int = 3

    kkt_stall_iterations: int = 10
    """Stop, with the status ``stalled``, when, over this many iterations at
    feasible points, the best KKT residual has not decreased by 10 % and the
    iterates moved less than 1e-3 of the ranges: the precision the problem
    reaches, short of ``kkt_tolerance``."""

    asymptote_init: float = 0.5
    """The distance of the first asymptotes, as a fraction of the ranges."""

    asymptote_increase: float = 1.2
    """Widening of the asymptotes of a variable moving the same way twice."""

    asymptote_decrease: float = 0.7
    """Narrowing of the asymptotes of an oscillating variable."""

    move_limit: float = 0.5
    """The largest move of a variable in one iteration, as a fraction of its range."""

    elastic_cost: float = 1000.0
    """The linear cost of the elastic variable of each constraint (Svanberg's c)."""

    elastic_quadratic: float = 1.0
    """Its quadratic cost (Svanberg's d)."""

    dual_solver: DualSolver = "auto"
    """A projected Newton method on the dual (its Hessian factorized: for sparse
    rows), L-BFGS-B on the dual, or a primal-dual interior point (small working
    sets); ``auto`` takes L-BFGS-B up to 10 constraints, the interior point up
    to ``dense_dual_threshold`` (as long as it stays cheap: ``n m²`` at most
    10⁷), then Newton for sparse rows, L-BFGS-B for dense ones."""

    dual_tolerance: float = 1e-5
    """The tolerance of L-BFGS-B on the dual (its projected gradient: the
    violation of the approximated constraints) near the optimum. Each subproblem
    is solved to a tenth of the last step, at most 1e-2: coarsely while the
    iterates move far, finely as they settle; never coarser than a tenth of the
    feasibility tolerances at the end, or feasibility could not be met."""

    dense_dual_threshold: int = 100
    """Constraints in the subproblem up to which ``auto`` may use the interior
    point."""

    max_inner_iterations: int = 20
    """GCMMA: inner iterations of an outer iteration, at most."""

    screening_margin: float = 0.3
    """The widest distance to activity of a constraint in the working set, the
    constraint divided by its largest change when one variable crosses its
    range: the same whatever its units."""

    screening_margin_min: float = 0.05
    """The narrowest one, as the iterates converge."""

    keep_factor: float = 1.5
    """A constraint of the last working set stays in it within this many times
    the screening margin of activity (hysteresis: no churn at the margin)."""

    max_working_set: int = 20_000
    """Rows per iteration, at most; the constraints with the largest values kept.

    The constraints active in the last subproblem are always kept, beyond it if
    need be.
    """

    max_screening_repairs: int = 3
    """Subproblems solved again, at most, when a step violates a constraint out
    of the working set (outside the feasible domain: when it makes one worse)."""

    violated_share: float = 0.25
    """The share of the inequality constraints violated at the iterate above
    which the run is outside the feasible domain, in the sense of the working
    set: it keeps the most violated constraints only (``violated_working_set``)
    and a step is checked against the constraints it makes worse, not against
    all the violated ones, until the share falls under half of this (1: never)."""

    violated_working_set: float = 0.1
    """Outside the feasible domain, the share of the inequality constraints the
    working set holds, the most violated first (at least 100 rows), the active
    ones of the last subproblem always kept."""

    row_refresh: RowRefresh = "always"
    """Compute every row at the iterate, or reuse the young rows of the
    constraints far from activity (``near_active``)."""

    fresh_margin: float = 0.05
    """``near_active``: the rows of the constraints within this distance to
    activity are always computed at the iterate."""

    max_row_age: int = 3
    """``near_active``: a row older than this many iterations is computed again."""

    max_row_step: float = 0.05
    """``near_active``: nor reused once the iterate moved more than this share of
    the ranges since it was computed."""

    row_dtype: RowDtype = "float64"
    """The precision the rows are kept and multiplied in: float32 halves their
    memory and the time of the products, but its sums round the dual of the
    subproblem at about 1e-10, which stops its line searches short of the
    finest tolerance (the restoration of feasibility then ends slightly
    infeasible)."""

    row_batch_size: int = 0
    """Rows per request to the problem (0: all the rows of an iteration at once)."""

    eq_tolerance: float = 1e-5
    """An equality constraint ``h = 0`` is met within this."""

    equality_band_decrease: float = 0.5
    """Each equality constraint is replaced by ``h - ε <= 0`` and ``-h - ε <= 0``;
    the band ``ε`` starts at ``max(1, max |h(x0)|)`` and is multiplied by this at
    each iteration, down to ``eq_tolerance``: a thin band from the start leaves
    MMA no room to move along the constraint."""

    max_equality: int = 100
    """Equality constraints, at most."""

    max_row_evaluations: int = 0
    """A budget of constraint gradients: the run stops, with the status
    ``max_rows``, once it has asked for this many (0: no budget)."""

    restoration_iterations: int = 20
    """Iterations spent, at most, bringing an infeasible run back within the
    constraints: when its objective has settled, or before ``max_iter`` or
    ``max_evaluations``, the optimizer switches to GCMMA, halves its move limit
    at each iteration and raises the cost of the elastic variables, until the
    point is feasible (0: never)."""

    descent_iterations: int = 0
    """The path through the constraints (0: off, the default). The run starts
    with a descent of at most this many iterations: the elastic variables cost
    a thousandth of ``elastic_cost``, so the objective dominates and the design
    goes down from a neutral start, through the constraints, towards the
    lightest design (for a structure, the fully stressed one, every member at
    its limit). It ends when the objective has settled, and the restoration of
    feasibility (``restoration_iterations``) brings the design back within the
    constraints before the normal iterations resume."""

    max_evaluations: int = 0
    """The evaluations the run may make, when a driver stops it on them
    (GEMSEO's ``max_iter``); 0: none. The last iterations are restored once the
    evaluations left, at the rate of the run, would last no more than the
    restoration: GCMMA makes several evaluations per iteration, and a budget
    of evaluations ends long before ``max_iter`` iterations."""

    jacobian_mode: JacobianMode = "rows"
    """How the rows of the constraints are obtained: asked for one by one, the
    working set only (``rows``, the default); or from a colored Jacobian, a few
    tens of directional derivatives when the problem gives a sparsity pattern,
    with the exact rows of the constraints within ``fresh_margin`` of activity
    or of a leakage above ``leakage_tolerance`` (``hybrid``: optional, it asks
    for a pattern). A mode taking every row from the colored Jacobian was
    removed: its optimum is that of the colored Jacobian, off wherever the
    constraints are not local (spec § 3.9)."""

    pattern_margin: int = 1
    """``hybrid``: the widenings of the pattern before coloring (the
    variables of a color farther apart, leaking less into each other)."""

    color_overlap: int = 2
    """``hybrid``: the colorings, each entry read once per coloring; their
    spread estimates the leakage (none with 1)."""

    leakage_tolerance: float = 1e-2
    """``hybrid``: a constraint whose colored row has an estimated leakage
    above this share of its norm gets its exact row."""

    jacobian_refresh: int = 1
    """``hybrid``: the iterations between two colorings; in between, the
    Jacobian follows Schubert's update, with no evaluation."""

    difference_step: float = 1e-6
    """``hybrid``, without a tangent mode: the step of the forward finite
    differences, relative to the ranges."""

    def __post_init__(self) -> None:
        positive = (
            "max_iter",
            "stall_iterations",
            "kkt_stall_iterations",
            "asymptote_init",
            "move_limit",
            "elastic_cost",
            "elastic_quadratic",
            "max_inner_iterations",
            "screening_margin",
            "screening_margin_min",
            "keep_factor",
            "max_working_set",
            "violated_working_set",
            "eq_tolerance",
            "dual_tolerance",
            "color_overlap",
            "jacobian_refresh",
            "difference_step",
        )
        for name in positive:
            if getattr(self, name) <= 0:
                msg = f"{name} must be positive, not {getattr(self, name)}."
                raise SettingsError(msg)
        non_negative = (
            "kkt_tolerance",
            "ineq_tolerance",
            "ftol_rel",
            "xtol_rel",
            "max_screening_repairs",
            "violated_share",
            "fresh_margin",
            "max_row_age",
            "max_row_step",
            "row_batch_size",
            "max_equality",
            "pattern_margin",
            "leakage_tolerance",
            "restoration_iterations",
            "descent_iterations",
            "max_row_evaluations",
            "max_evaluations",
        )
        for name in non_negative:
            if getattr(self, name) < 0:
                msg = f"{name} must be zero or positive, not {getattr(self, name)}."
                raise SettingsError(msg)
        if self.asymptote_increase < 1:
            msg = (
                f"asymptote_increase must be at least 1, not {self.asymptote_increase}."
            )
            raise SettingsError(msg)
        if not 0 < self.asymptote_decrease <= 1:
            msg = (
                f"asymptote_decrease must be in ]0, 1], not {self.asymptote_decrease}."
            )
            raise SettingsError(msg)
        if self.violated_working_set > 1:
            msg = (
                "violated_working_set is a share of the constraints, "
                f"not {self.violated_working_set}."
            )
            raise SettingsError(msg)
        if self.move_limit > 1:
            msg = f"move_limit is a fraction of the ranges, not {self.move_limit}."
            raise SettingsError(msg)
        if not 0 < self.equality_band_decrease <= 1:
            msg = (
                "equality_band_decrease must be in ]0, 1], "
                f"not {self.equality_band_decrease}."
            )
            raise SettingsError(msg)
        if self.screening_margin_min > self.screening_margin:
            msg = (
                f"screening_margin_min ({self.screening_margin_min}) must not "
                f"exceed screening_margin ({self.screening_margin})."
            )
            raise SettingsError(msg)
        if self.row_dtype not in ("float32", "float64"):
            msg = f"row_dtype must be float32 or float64, not {self.row_dtype}."
            raise SettingsError(msg)
        if self.row_refresh not in ("always", "near_active"):
            msg = f"row_refresh must be always or near_active, not {self.row_refresh}."
            raise SettingsError(msg)
        if self.jacobian_mode not in ("rows", "hybrid"):
            msg = f"jacobian_mode must be rows or hybrid, not {self.jacobian_mode}."
            raise SettingsError(msg)
        if self.method not in ("mma", "gcmma"):
            msg = f"method must be mma or gcmma, not {self.method}."
            raise SettingsError(msg)
        if self.dual_solver not in ("auto", "newton", "lbfgsb", "interior_point"):
            msg = (
                "dual_solver must be auto, newton, lbfgsb or interior_point, "
                f"not {self.dual_solver}."
            )
            raise SettingsError(msg)


SETTING_NAMES = tuple(field.name for field in fields(Settings))
