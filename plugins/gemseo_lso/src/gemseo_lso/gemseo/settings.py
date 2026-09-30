"""The settings of ``LSO_MMA`` and ``LSO_GCMMA`` (spec § 4).

A Pydantic model deriving from GEMSEO's ``BaseOptimizerSettings``, mapped onto
the frozen settings of the core (``gemseo_lso.core.Settings``). GEMSEO keeps
its own stopping criteria (``max_iter``, which counts evaluations, ``max_time``,
``ftol_rel``, ``xtol_rel``…), its feasibility tolerances and the normalization
of the design space; ``store_jacobian`` is forced to False: the rows live in
the cache of the optimizer, and a whole Jacobian of 10⁵ × 10⁵ would not fit.
"""

from collections.abc import Callable
from dataclasses import fields
from typing import Any
from typing import ClassVar
from typing import Literal

from gemseo.algos.opt.base_optimizer_settings import BaseOptimizerSettings
from pydantic import Field
from pydantic import NonNegativeFloat
from pydantic import NonNegativeInt
from pydantic import PositiveFloat
from pydantic import PositiveInt
from pydantic import field_validator
from pydantic import model_validator

from gemseo_lso.core.settings import Settings
from gemseo_lso.core.settings import SettingsError

SparsityPattern = Callable[[list[tuple[str, int]], list[tuple[str, int]]], Any]
"""``pattern(variables, constraints)``: the sparsity pattern of the inequality
constraints, a ``scipy.sparse`` boolean matrix (constraints × variables), from
the design variables and the inequality constraints as ``(name, size)`` in
GEMSEO's order."""

_GEMSEO_OWNED = {"method", "max_iter", "stall_iterations", "max_evaluations"}
"""Core settings GEMSEO handles itself, or the algorithm sets."""


class BaseLSOSettings(BaseOptimizerSettings):  # type: ignore[misc]
    """The settings common to ``LSO_MMA`` and ``LSO_GCMMA``."""

    _TARGET_CLASS_NAME: ClassVar[str] = ""

    store_jacobian: bool = Field(
        default=False,
        description="Always False: the optimizer keeps the rows it asked for; "
        "a whole Jacobian of large problems would not fit in memory.",
    )

    ineq_tolerance: NonNegativeFloat = Field(
        default=1e-5,
        description="A constraint is satisfied when g <= ineq_tolerance.",
    )

    eq_tolerance: NonNegativeFloat = Field(
        default=1e-5,
        description="An equality constraint h = 0 is met within this.",
    )

    kkt_tolerance: NonNegativeFloat = Field(
        default=1e-3,
        description="Stop when stationarity and complementarity, relative to the "
        "largest component of the gradient of the objective, are below this.",
    )

    kkt_stall_iterations: PositiveInt = Field(
        default=10,
        description="Iterations without progress of the KKT residual before MMA "
        "switches to GCMMA (iterates still moving) or the run stops as stalled "
        "(iterates settled).",
    )

    asymptote_init: PositiveFloat = Field(
        default=0.5,
        description="The distance of the first asymptotes, as a fraction of the "
        "ranges.",
    )

    asymptote_increase: float = Field(
        default=1.2,
        ge=1.0,
        description="Widening of the asymptotes of a variable moving the same way "
        "twice.",
    )

    asymptote_decrease: float = Field(
        default=0.7,
        gt=0.0,
        le=1.0,
        description="Narrowing of the asymptotes of an oscillating variable.",
    )

    move_limit: float = Field(
        default=0.5,
        gt=0.0,
        le=1.0,
        description="The largest move of a variable in one iteration, as a "
        "fraction of its range.",
    )

    elastic_cost: PositiveFloat = Field(
        default=1000.0,
        description="The linear cost of the elastic variable keeping each "
        "subproblem feasible.",
    )

    elastic_quadratic: PositiveFloat = Field(
        default=1.0, description="The quadratic cost of the elastic variables."
    )

    dual_solver: Literal["auto", "newton", "lbfgsb", "interior_point"] = Field(
        default="auto",
        description="The solver of the subproblems: an interior point up to "
        "dense_dual_threshold constraints, then a projected Newton method on the "
        "dual with sparse rows, L-BFGS-B with dense ones (auto).",
    )

    dual_tolerance: PositiveFloat = Field(
        default=1e-5,
        description="The finest tolerance of the dual of the subproblems.",
    )

    dense_dual_threshold: NonNegativeInt = Field(
        default=100,
        description="Constraints in a subproblem up to which auto uses the "
        "interior point.",
    )

    max_inner_iterations: PositiveInt = Field(
        default=20,
        description="GCMMA: inner iterations of an outer iteration, at most.",
    )

    screening_margin: PositiveFloat = Field(
        default=0.3,
        description="The widest distance to activity of a constraint in the "
        "working set.",
    )

    screening_margin_min: PositiveFloat = Field(
        default=0.05,
        description="The narrowest one, as the iterates converge.",
    )

    keep_factor: PositiveFloat = Field(
        default=1.5,
        description="A constraint of the last working set stays in it within this "
        "many times the screening margin of activity.",
    )

    max_working_set: PositiveInt = Field(
        default=20_000,
        description="Rows per iteration, at most; the constraints active in the "
        "last subproblem are always kept.",
    )

    max_screening_repairs: NonNegativeInt = Field(
        default=3,
        description="Subproblems solved again, at most, when a step violates a "
        "constraint out of the working set.",
    )

    row_refresh: Literal["always", "near_active"] = Field(
        default="always",
        description="Compute every row at the iterate, or reuse the young rows of "
        "the constraints far from activity (near_active).",
    )

    fresh_margin: NonNegativeFloat = Field(
        default=0.05,
        description="The rows of the constraints within this distance to activity "
        "are always computed at the iterate (near_active, hybrid).",
    )

    max_row_age: NonNegativeInt = Field(
        default=3,
        description="near_active: a row older than this many iterations is "
        "computed again.",
    )

    max_row_step: NonNegativeFloat = Field(
        default=0.05,
        description="near_active: nor reused once the iterate moved more than "
        "this share of the ranges.",
    )

    row_dtype: Literal["float32", "float64"] = Field(
        default="float64",
        description="The precision the rows are kept and multiplied in.",
    )

    row_batch_size: NonNegativeInt = Field(
        default=0,
        description="Rows per request to the model (0: all at once).",
    )

    equality_band_decrease: float = Field(
        default=0.5,
        gt=0.0,
        le=1.0,
        description="The band of the equality constraints shrinks by this factor "
        "at each iteration, down to eq_tolerance.",
    )

    max_equality: NonNegativeInt = Field(
        default=100, description="Equality constraints, at most."
    )

    max_row_evaluations: NonNegativeInt = Field(
        default=0,
        description="A budget of constraint gradients: the run stops once it has "
        "asked for this many (0: no budget).",
    )

    save_state: str | None = Field(
        default=None,
        description="An HDF5 file where the state of the optimizer is saved at "
        "the end of the run, to resume it with resume_from.",
    )

    resume_from: str | None = Field(
        default=None,
        description="An HDF5 file of a saved state: the run goes on from it, with "
        "its asymptotes, multipliers and history, instead of starting.",
    )

    restoration_iterations: NonNegativeInt = Field(
        default=20,
        description="Iterations spent, at most, bringing an infeasible run back "
        "within the constraints once its objective has settled or before "
        "max_iter: GCMMA, a move limit halved at each iteration, a higher cost of "
        "the elastic variables (0: never).",
    )

    descent_iterations: NonNegativeInt = Field(
        default=0,
        description="The path through the constraints (0: off). The run starts "
        "with a descent of at most this many iterations, the elastic variables "
        "costing a thousandth of elastic_cost: the design goes down from a "
        "neutral start, through the constraints, towards the lightest design "
        "(the fully stressed one, for a structure), until the objective has "
        "settled. Its feasibility is then restored (restoration_iterations) "
        "before the normal iterations resume.",
    )

    jacobian_mode: Literal["rows", "hybrid"] = Field(
        default="rows",
        description="How the gradients of the constraints are obtained: those of "
        "the working set, one by one (rows); or a colored Jacobian with the exact "
        "rows of the constraints near activity (hybrid), which needs "
        "sparsity_pattern.",
    )

    sparsity_pattern: SparsityPattern | None = Field(
        default=None,
        description="hybrid: a function returning the sparsity pattern of "
        "the inequality constraints, a scipy.sparse boolean matrix (constraints × "
        "variables), from the design variables and the inequality constraints as "
        "(name, size).",
    )

    pattern_margin: NonNegativeInt = Field(
        default=1,
        description="hybrid: widenings of the pattern before the first coloring.",
    )

    color_overlap: PositiveInt = Field(
        default=2,
        description="hybrid: colorings, each on the pattern widened once "
        "more; their spread estimates the error of the entries.",
    )

    leakage_tolerance: NonNegativeFloat = Field(
        default=1e-2,
        description="hybrid: exact rows for the constraints whose colored row "
        "leaks more than this share of its norm.",
    )

    jacobian_refresh: PositiveInt = Field(
        default=1,
        description="hybrid: iterations between two colorings (Schubert "
        "updates in between).",
    )

    difference_step: PositiveFloat = Field(
        default=1e-6,
        description="hybrid without a tangent mode: the step of the finite "
        "differences, relative to the ranges.",
    )

    @field_validator("store_jacobian")
    @classmethod
    def _no_stored_jacobian(cls, value: bool) -> bool:
        if value:
            msg = (
                "store_jacobian must be False: the optimizer keeps the rows it "
                "asked for."
            )
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _core_settings_are_valid(self) -> "BaseLSOSettings":
        try:
            core_settings(self, "mma")
        except SettingsError as error:
            raise ValueError(str(error)) from None
        return self


class LSO_MMA_Settings(BaseLSOSettings):  # noqa: N801
    """The settings of ``LSO_MMA``."""

    _TARGET_CLASS_NAME: ClassVar[str] = "LSO_MMA"


class LSO_GCMMA_Settings(BaseLSOSettings):  # noqa: N801
    """The settings of ``LSO_GCMMA``."""

    _TARGET_CLASS_NAME: ClassVar[str] = "LSO_GCMMA"


def core_settings(settings: BaseLSOSettings, method: str) -> Settings:
    """The settings of the core, from those of GEMSEO.

    GEMSEO stops the run on ``max_iter`` (it counts evaluations, more than the
    core's iterations: the core never stops first, but gets it as
    ``max_evaluations`` to restore feasibility before the end) and
    ``max_time``. ``ftol_rel`` and ``xtol_rel``
    are the core's, over ``stop_crit_n_x`` outer iterations at feasible points:
    GEMSEO's compare evaluations, of which GCMMA makes several per iteration
    (``ftol_abs`` and ``xtol_abs`` are not used).
    """
    values = {
        item.name: getattr(settings, item.name)
        for item in fields(Settings)
        if item.name not in _GEMSEO_OWNED and hasattr(settings, item.name)
    }
    return Settings(
        method=method,  # type: ignore[arg-type]
        max_iter=settings.max_iter,
        max_evaluations=settings.max_iter,
        stall_iterations=settings.stop_crit_n_x,
        **values,
    )
