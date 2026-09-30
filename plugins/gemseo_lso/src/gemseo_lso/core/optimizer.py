"""The optimizer: MMA and GCMMA, one outer iteration per step (spec § 3.2, § 5).

Each iteration uses the rows of a working set of constraints only (those
close to activity), checks the step against all the constraint values, and
solves the subproblem again with the constraints it would violate. The rows
are asked for one by one (``jacobian_mode`` ``rows``, the default), or, when
asked for and the problem gives a sparsity pattern, from a colored Jacobian
and the exact rows of the constraints near activity (``hybrid``: spec § 3.9).

Example:
    >>> import numpy as np
    >>> from gemseo_lso.core.problem import DenseProblem
    >>> problem = DenseProblem(
    ...     x0=np.array([1.5, 1.5]),
    ...     lower=np.zeros(2),
    ...     upper=np.full(2, 2.0),
    ...     objective=lambda x: float(x @ x),
    ...     objective_gradient=lambda x: 2 * x,
    ...     constraints=lambda x: np.array([1.0 - x.sum()]),
    ...     constraint_jacobian=lambda x: -np.ones((1, 2)),
    ... )
    >>> result = Optimizer(problem).run()
    >>> result.status, np.round(result.x, 4)
    ('converged', array([0.5, 0.5]))
"""

import time
from collections.abc import Callable
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import replace
from typing import Any
from typing import TypeVar

import numpy as np
from numpy.typing import NDArray
from scipy import sparse

from gemseo_lso.core.approximation import MMA_RHO
from gemseo_lso.core.approximation import Approximation
from gemseo_lso.core.approximation import asymptotes
from gemseo_lso.core.approximation import gcmma_rho
from gemseo_lso.core.approximation import move_limits
from gemseo_lso.core.arrays import Array
from gemseo_lso.core.arrays import Indices
from gemseo_lso.core.arrays import Rows
from gemseo_lso.core.arrays import is_sparse
from gemseo_lso.core.arrays import stack_rows
from gemseo_lso.core.arrays import times_rows
from gemseo_lso.core.coloring import Coloring
from gemseo_lso.core.coloring import PatternError
from gemseo_lso.core.coloring import check_pattern
from gemseo_lso.core.coloring import color
from gemseo_lso.core.dual import SubproblemSolution
from gemseo_lso.core.dual import checked
from gemseo_lso.core.dual import solve_dual
from gemseo_lso.core.dual import solve_interior_point
from gemseo_lso.core.dual import solve_newton
from gemseo_lso.core.problem import LargeScaleProblem
from gemseo_lso.core.report import Report
from gemseo_lso.core.report import Result
from gemseo_lso.core.rows import RowCache
from gemseo_lso.core.screening import screening_margin
from gemseo_lso.core.screening import working_set
from gemseo_lso.core.settings import Settings
from gemseo_lso.core.sparse_jacobian import ColoredJacobian
from gemseo_lso.core.sparse_jacobian import Derivatives
from gemseo_lso.core.sparse_jacobian import colored_jacobian
from gemseo_lso.core.state import State

CONSERVATIVE_TOLERANCE = 1e-9
"""GCMMA: how far below its approximation a function may be, relatively."""

ADAPTIVE_DUAL_FACTOR = 0.1
"""Each subproblem is solved to this share of the last step (not of the KKT
residual: it depends on the accuracy of the multipliers, so on the dual)..."""

ADAPTIVE_DUAL_MAX = 1e-2
"""...at most this; at least ``dual_tolerance``, and a tenth of the
feasibility tolerances."""

FEW_CONSTRAINTS = 10
"""A subproblem of at most this many constraints has a dual of at most this
many variables: L-BFGS-B solves it in a few evaluations..."""

MANY_VARIABLES = 500
"""...when there are at least this many variables. The interior point, about a
hundred Newton iterations whatever the size, took 6.5 s against 0.2 s on
Svanberg's beam of 100 segments and did not finish in 250 s at 1,000; below,
its multipliers are the more accurate (Sellar's problem, and the beam of 5
segments with wide bounds, which L-BFGS-B does not solve in 300 iterations)."""

INTERIOR_POINT_WORK = 10_000_000
"""The interior point forms a matrix of ``m²`` entries from ``n`` variables at
each of its iterations: ``auto`` leaves it when ``n m²`` exceeds this."""

RESTORATION_MARGIN = 1e-4
"""The restoration of the last iterations tightens the inequality constraints
of its subproblems by this much (in the units of the subproblem, on a scale
of 1) and solves their dual to it: the approximated constraints end at most 0.
Solved to the finest tolerance instead, the dual of L-BFGS-B took 2,000 to
6,000 evaluations per iteration against 20 to 60 before; tightened, 6 to 9
times fewer, for an objective larger by about this share. Only at the end: a
restoration in the middle of a run, its iterates pushed off the active
constraints by the margin, alternated with the next iterations and kept the
run from converging."""

FIRST_STEP = 1e-2
"""The step assumed before the first one, for the tolerance of the dual."""

STALL_STEP = 1e-3
"""Iterates moving less than this share of the ranges have settled."""

KKT_SCALE_FLOOR = 1e-3
"""The KKT residual is measured against the largest term of the gradient of
the Lagrangian, never less than this share of the gradient of the objective at
the start (it goes to zero at an unconstrained optimum)."""

STALL_DECREASE = 0.9
"""The best KKT residual must fall below this share of its former best within
``kkt_stall_iterations`` iterations, or the run has stalled."""

RESTORE_SETTLED = 1e-3
"""An infeasible run whose objective changed less than this, relatively, over
``kkt_stall_iterations`` iterations has settled: its feasibility is restored."""

RESTORE_SHRINK = 0.5
"""The move limit is multiplied by this at each iteration of restoration..."""

RESTORE_MIN_MOVE = 1e-3
"""...down to this share of the ranges."""

RESTORE_ELASTIC = 10.0
"""The cost of the elastic variables is multiplied by this while restoring."""

DESCENT_ELASTIC = 1e-3
"""The cost of the elastic variables is multiplied by this during the descent
through the constraints: they hardly hold the design back."""

DESCENT_SETTLED = 1e-2
"""The descent ends when the objective falls by less than this share of itself
in an iteration."""

BOUND_COSTS = 5
"""The variables at or near a bound whose exit costs the least, that a report
lists."""

NEAR_BOUND = 0.01
"""A variable this close to a bound, as a share of its range, is near it: the
bar 6 of the 10-bar truss, 0.7 % from its bound at the end of a descent, decided
which of two optima the run reached."""

BOUND_TOLERANCE = 1e-8
"""A variable this close to a bound, relatively to its range, is at the bound
for the KKT conditions (the interior point stops just inside the bounds)."""


T = TypeVar("T")


class ProblemError(ValueError):
    """A problem the optimizer cannot solve; the message says why."""


@dataclass
class _Iteration:
    """What an outer iteration builds at its iterate."""

    working_set: Indices
    rows: Rows
    """The rows of the working set, then of the equality pairs."""

    values: Array
    """The values of the working set, then of the equality pairs."""

    multipliers: Array
    """The multipliers to start the subproblem from, in the same order."""


class Optimizer:
    """MMA or GCMMA on a problem, one outer iteration per step.

    Iterate over it to run it; replace ``settings`` between two steps to
    change how it goes on; save ``state`` to resume later.

    Args:
        problem: The problem.
        settings: How to run.
        state: A state to resume from (see ``State.load``); else the run starts
            at the starting point of the problem.
    """

    def __init__(
        self,
        problem: LargeScaleProblem,
        settings: Settings | None = None,
        state: State | None = None,
    ) -> None:
        self.problem = problem
        self.settings = settings or Settings()
        lower, upper = problem.lower, problem.upper
        if not (np.all(np.isfinite(lower)) and np.all(np.isfinite(upper))):
            msg = "Every variable needs finite bounds."
            raise ProblemError(msg)
        if np.any(upper <= lower):
            msg = "Every upper bound must be above its lower bound."
            raise ProblemError(msg)
        self.ranges: Array = upper - lower
        self.cache = RowCache(lower.size)
        self.jacobian: ColoredJacobian | None = None
        """``hybrid``: the colored Jacobian of the inequality constraints."""

        self._pattern: sparse.csr_matrix | None = None
        self._coloring: Coloring | None = None
        self._coloring_key: tuple[int, int] = (-1, -1)
        self._model_time = 0.0
        self.stationarity = np.zeros(0)
        self._bounds: tuple[int, int, tuple[tuple[int, float, float], ...]] = (
            0,
            0,
            (),
        )
        self._near_end = False
        """Whether the iteration is among the last ones, restored."""
        """The projected gradient of the Lagrangian at the iterate, per variable,
        from the last KKT residual: where the residual comes from."""
        self._rows_computed = 0
        self._rows_reused = 0
        self._products = 0
        if state is None:
            x = np.clip(problem.x0, lower, upper)
            objective, constraints, equalities = problem.values(x)
            state = State(
                x=x,
                objective=objective,
                constraints=constraints,
                multipliers=np.zeros(constraints.size),
                equalities=equalities,
                equality_multipliers=np.zeros(2 * equalities.size),
                equality_band=max(
                    self.settings.eq_tolerance,
                    1.0,
                    float(np.abs(equalities).max(initial=0.0)),
                ),
                history=[objective],
            )
        if state.equalities.size > self.settings.max_equality:
            msg = (
                f"{state.equalities.size} equality constraints: at most "
                f"{self.settings.max_equality} are supported (max_equality)."
            )
            raise ProblemError(msg)
        self.state = state
        self._remember_if_best()
        if self.settings.jacobian_mode != "rows":
            self._colors()

    @property
    def finished(self) -> bool:
        """Whether the run has ended."""
        return self.state.status != "running"

    def stop(self, reason: str = "stopped on request") -> None:
        """End the run after the current step."""
        if not self.finished:
            self.state.status = "stopped"
            self.state.message = reason

    def move(self, x: Array) -> None:
        """Go on from another point, keeping the state: a pilot steering the run.

        One evaluation. The past iterates and the asymptotes move with the
        point: the asymptotes keep their spreads and their trend, the
        multipliers and the working set stay; the next step starts from ``x``.
        """
        state, problem = self.state, self.problem
        x = np.clip(np.asarray(x, dtype=float), problem.lower, problem.upper)
        shift = x - state.x
        objective, constraints, equalities = self._timed(problem.values, x)
        state.evaluations += 1
        for name in ("x_previous", "x_before", "lower_asymptote", "upper_asymptote"):
            value = getattr(state, name)
            if value is not None:
                setattr(state, name, value + shift)
        state.constraints_previous = state.constraints
        state.x = x
        state.objective = objective
        state.constraints = constraints
        state.equalities = equalities
        self._remember_if_best()

    def __iter__(self) -> Iterator[Report]:
        while not self.finished:
            yield self.step()

    def run(self) -> Result:
        """Run to the end."""
        for _ in self:
            pass
        return self.result

    @property
    def result(self) -> Result:
        """Where the run is, or how it ended.

        The best feasible point met, when the last one is infeasible or worse.
        """
        state = self.state
        x, objective, max_constraint = state.x, state.objective, self._max_constraint()
        message = state.message
        best = state.best_x is not None and (
            not self._feasible() or state.best_objective < state.objective
        )
        if best:
            assert state.best_x is not None
            x, objective = state.best_x, state.best_objective
            max_constraint = state.best_max_constraint
            message = (
                f"{message} The best feasible point, of iteration "
                f"{state.best_iteration}, is returned."
            ).strip()
        return Result(
            x=x,
            objective=objective,
            max_constraint=max_constraint,
            iterations=state.iteration,
            evaluations=state.evaluations,
            row_evaluations=state.row_evaluations,
            status=state.status,
            message=message,
            directional_derivatives=state.directional_derivatives,
        )

    def step(self) -> Report:
        """One outer iteration: rows, subproblem, step."""
        if self.finished:
            msg = "The run has ended."
            raise RuntimeError(msg)
        start = time.perf_counter()
        settings, state, problem = self.settings, self.state, self.problem
        x = state.x
        self._model_time = 0.0
        self._rows_computed = 0
        self._rows_reused = 0
        self._products = 0

        # The screening in the units of the subproblem: a margin means the
        # same whatever the units of the constraints.
        if state.constraints.size and not np.any(self._known_scales()):
            # No scale known yet: the row of the largest constraint gives one.
            first = np.array([int(np.argmax(state.constraints))])
            row = self._exact_rows(first, np.ones(1, dtype=bool))
            self._known_scales()[first] = _row_scales(row, self.ranges)
        scales = self._screening_scales()
        previous = state.constraints_previous
        margin = screening_margin(
            state.constraints / scales,
            None if previous is None else previous / scales,
            settings,
        )
        indices = working_set(
            state.constraints / scales,
            margin,
            state.working_set,
            state.multipliers * scales / (state.objective_scale or 1.0),
            settings,
        )
        gradient = self._timed(problem.objective_gradient, x)
        if settings.jacobian_mode != "rows":
            self._color_jacobian()
        equality_rows = (
            self._timed(problem.equality_rows, x).astype(settings.row_dtype)
            if state.equalities.size
            else np.zeros((0, x.size), dtype=settings.row_dtype)
        )
        state.row_evaluations += state.equalities.size
        iteration = self._iteration(
            indices,
            equality_rows,
            np.concatenate([state.multipliers[indices], state.equality_multipliers]),
        )

        if not state.gradient_scale:
            state.gradient_scale = float(np.max(np.abs(gradient), initial=0.0)) or 1.0
        if not state.objective_scale:
            state.objective_scale = (
                float(np.max(np.abs(gradient) * self.ranges, initial=0.0)) or 1.0
            )
        scale = state.objective_scale
        kkt = self._kkt_residual(gradient, iteration)
        state.kkt_history.append(kkt)
        self._update_descent()
        self._switch_if_cycling()
        if self._feasible() and state.descent <= 0:
            if kkt <= settings.kkt_tolerance:
                state.status = "converged"
                state.message = f"KKT conditions met within {settings.kkt_tolerance:g}."
                return self._report(0.0, 0, 0, kkt, iteration, start)
            if self._stalled():
                return self._report(0.0, 0, 0, kkt, iteration, start)
        self._update_restoration()
        active = self._active_settings()
        last_step = state.step_history[-1] if state.step_history else FIRST_STEP
        dual_tolerance = min(ADAPTIVE_DUAL_MAX, ADAPTIVE_DUAL_FACTOR * last_step)
        margin = 0.0
        if state.restoration:
            # A tenth of the last step (1e-4 for steps of 1e-3) left violations
            # above the feasibility tolerance, whatever the move limit: the
            # approximated constraints met to the finest (_solve), or, in the
            # last iterations, tightened by what the dual may leave of them.
            dual_tolerance = 0.0
            if self._near_end:
                dual_tolerance = margin = RESTORATION_MARGIN

        lower_asymptote, upper_asymptote = asymptotes(
            x,
            state.x_previous,
            state.x_before,
            state.lower_asymptote,
            state.upper_asymptote,
            self.ranges,
            settings,
        )
        alpha, beta = move_limits(
            x, lower_asymptote, upper_asymptote, problem.lower, problem.upper, active
        )

        def approximate(iteration: _Iteration) -> tuple[Approximation, Array]:
            # Every function of the subproblem on a scale of 1: its multipliers
            # and its tolerances mean the same whatever the units of the
            # problem. A constraint is divided by its largest change when one
            # variable crosses its range, the objective by its own at the start.
            scales = _row_scales(iteration.rows, self.ranges)
            known = self._known_scales()
            known[iteration.working_set] = scales[: iteration.working_set.size]
            rows = _divide_rows(iteration.rows, scales)
            if self.method == "gcmma":
                objective_rho = float(
                    gcmma_rho(gradient[None, :] / scale, self.ranges)[0]
                )
                constraint_rho = gcmma_rho(rows, self.ranges)
            else:
                objective_rho = MMA_RHO
                constraint_rho = np.full(iteration.values.size, MMA_RHO)
            approximation = Approximation(
                x=x,
                lower_asymptote=lower_asymptote,
                upper_asymptote=upper_asymptote,
                alpha=alpha,
                beta=beta,
                ranges=self.ranges,
                objective=state.objective / scale,
                objective_gradient=gradient / scale,
                constraints=_tightened(
                    iteration.values / scales, iteration.working_set.size, margin
                ),
                rows=rows,
                objective_rho=objective_rho,
                constraint_rho=constraint_rho,
            )
            return approximation, scales

        approximation, scales = approximate(iteration)
        multipliers = iteration.multipliers
        inner = repairs = 0
        while True:
            solution = self._solve(
                approximation, scales, multipliers, dual_tolerance, active
            )
            objective, constraints, equalities = self._timed(problem.values, solution.x)
            state.evaluations += 1
            multipliers = solution.multipliers
            outside = np.setdiff1d(
                np.flatnonzero(constraints > settings.ineq_tolerance),
                iteration.working_set,
            )
            if outside.size and repairs < settings.max_screening_repairs:
                # A screened-out constraint would be violated: into the subproblem.
                repairs += 1
                iteration = self._repair(iteration, outside, multipliers, equality_rows)
                approximation, scales = approximate(iteration)
                multipliers = iteration.multipliers
                continue
            if self.method == "gcmma" and inner < settings.max_inner_iterations:
                values = self._values(iteration.working_set, constraints, equalities)
                if self._tighten(
                    approximation, solution.x, objective / scale, values / scales
                ):
                    inner += 1
                    continue
            break

        previous = state.constraints
        self._accept(
            solution,
            iteration,
            objective,
            constraints,
            equalities,
            lower_asymptote,
            upper_asymptote,
        )
        if self.jacobian is not None and settings.jacobian_refresh > 1:
            self.jacobian.update(state.x - x, constraints - previous)
        self._remember_if_best()
        step = float(np.max(np.abs(solution.x - x) / self.ranges, initial=0.0))
        state.step_history.append(step)
        self._check_stop(step)
        return self._report(step, inner, repairs, kkt, iteration, start)

    def _timed(self, function: Callable[..., T], *args: Any) -> T:
        """Call the problem, counting the time spent in it."""
        start = time.perf_counter()
        result = function(*args)
        self._model_time += time.perf_counter() - start
        return result

    def _colors(self) -> Coloring:
        """The colorings of the pattern, made again when their settings change.

        Raises:
            ProblemError: When the problem gives no pattern, or a wrong one.
        """
        settings, state = self.settings, self.state
        if self._pattern is None:
            sparsity = getattr(self.problem, "sparsity", None)
            given = sparsity() if sparsity is not None else None
            if given is None:
                msg = (
                    f"jacobian_mode {settings.jacobian_mode} needs a sparsity "
                    "pattern, which the problem does not give: use the rows mode."
                )
                raise ProblemError(msg)
            try:
                self._pattern = check_pattern(
                    given, (state.constraints.size, state.x.size)
                )
            except PatternError as error:
                raise ProblemError(str(error)) from None
        key = (settings.pattern_margin, settings.color_overlap)
        if self._coloring is None or key != self._coloring_key:
            self._coloring = color(self._pattern, *key)
            self._coloring_key = key
            self.jacobian = None
        return self._coloring

    def _color_jacobian(self) -> None:
        """A new colored Jacobian at the iterate, every ``jacobian_refresh``."""
        state, settings, problem = self.state, self.settings, self.problem
        coloring = self._colors()
        if (
            self.jacobian is not None
            and state.iteration - self.jacobian.computed_at < settings.jacobian_refresh
        ):
            return
        derivatives = getattr(problem, "directional_derivatives", None)
        tangent: Derivatives | None = None
        if derivatives is not None:

            def timed(x: Array, directions: sparse.csc_matrix) -> Array | None:
                products: Array | None = self._timed(derivatives, x, directions)
                return products

            tangent = timed

        def values(x: Array) -> Array:
            return self._timed(problem.values, x)[1]

        jacobian, products, evaluations = colored_jacobian(
            tangent,
            values,
            state.x,
            state.constraints,
            coloring,
            problem.lower,
            problem.upper,
            settings.difference_step,
        )
        jacobian.computed_at = state.iteration
        self.jacobian = jacobian
        self._products += products
        state.directional_derivatives += products
        state.evaluations += evaluations

    def _iteration(
        self, indices: Indices, equality_rows: Rows, multipliers: Array
    ) -> _Iteration:
        """The rows and values of a working set and of the equality pairs."""
        state, settings = self.state, self.settings
        scaled = state.constraints[indices] / self._screening_scales()[indices]
        fresh = scaled >= -settings.fresh_margin
        if settings.jacobian_mode == "rows" or self.jacobian is None:
            rows = self._exact_rows(indices, fresh)
        else:
            rows = self.jacobian.rows(indices).astype(settings.row_dtype)
            leaky = self.jacobian.leakage[indices] > settings.leakage_tolerance
            exact = fresh | leaky
            if exact.any():
                rows = _merge(
                    rows, self._exact_rows(indices[exact], fresh[exact]), exact
                )
        return _Iteration(
            working_set=indices,
            rows=stack_rows([rows, equality_rows, -equality_rows], state.x.size),
            values=self._values(indices, state.constraints, state.equalities),
            multipliers=multipliers,
        )

    def _exact_rows(self, indices: Indices, fresh: NDArray[np.bool_]) -> Rows:
        """The rows of some constraints from the problem, or the cache."""
        state, settings = self.state, self.settings

        def fetch(chunk: Indices) -> Rows:
            rows = self._timed(self.problem.constraint_rows, state.x, chunk)
            return rows.astype(settings.row_dtype, copy=False)

        rows, computed, reused = self.cache.rows(
            indices, state.x, state.iteration, fresh, self.ranges, settings, fetch
        )
        self._rows_computed += computed
        self._rows_reused += reused
        state.row_evaluations += computed
        return rows

    def _known_scales(self) -> Array:
        """The scales of the constraints from their last rows, 0 if none."""
        state = self.state
        if state.constraint_scales is None:
            state.constraint_scales = np.zeros(state.constraints.size)
        return state.constraint_scales

    def _screening_scales(self) -> Array:
        """The scale of every constraint, or the median of the known ones.

        1 before any row.
        """
        known = self._known_scales()
        positive = known[known > 0]
        if not positive.size:
            return np.ones(known.size)
        return np.where(known > 0, known, float(np.median(positive)))

    def _values(self, indices: Indices, constraints: Array, equalities: Array) -> Array:
        """The values of a working set, then of the equality pairs."""
        band = self.state.equality_band
        return np.concatenate(
            [constraints[indices], equalities - band, -equalities - band]
        )

    def _repair(
        self,
        iteration: _Iteration,
        outside: Indices,
        multipliers: Array,
        equality_rows: Rows,
    ) -> _Iteration:
        """The working set with the constraints a step would violate."""
        indices = np.union1d(iteration.working_set, outside)
        size = iteration.working_set.size
        start = np.zeros(indices.size + multipliers.size - size)
        start[np.searchsorted(indices, iteration.working_set)] = multipliers[:size]
        start[indices.size :] = multipliers[size:]
        return self._iteration(indices, equality_rows, start)

    @property
    def method(self) -> str:
        """The method of the next iteration: GCMMA while restoring feasibility."""
        state = self.state
        if self.settings.method == "gcmma" or state.gcmma_since >= 0:
            return "gcmma"
        return "gcmma" if state.restoration else "mma"

    def _update_descent(self) -> None:
        """Start, go on with or end the descent through the constraints.

        The descent starts with the run when ``descent_iterations`` is set.
        It ends after that many iterations, or when the objective has stopped
        falling: the design is then near the lightest one the soft constraints
        allow, generally outside the feasible domain, and its feasibility is
        restored at once.
        """
        state, settings = self.state, self.settings
        if state.descent < 0 or not settings.descent_iterations:
            return
        state.descent += 1
        history = state.history
        settled = len(history) > 1 and (
            history[-2] - history[-1] <= DESCENT_SETTLED * max(abs(history[-2]), 1e-300)
        )
        if state.descent > settings.descent_iterations or settled:
            state.descent = -1
            if not self._feasible():
                state.restoration = 1

    def _update_restoration(self) -> None:
        """Start, go on with or end the restoration of feasibility.

        An infeasible run is restored once its objective has settled (it
        would otherwise oscillate outside the constraints until ``max_iter``),
        or when ``max_iter`` is ``restoration_iterations`` away (a quarter of
        the run at most), or the evaluations left in ``max_evaluations`` would
        last no more iterations, at the rate of the run: the last iterations
        are spent on feasibility, their moves shrinking, feasible or not. A
        restoration ends when the point is feasible, or after
        ``restoration_iterations`` iterations.
        """
        state, settings = self.state, self.settings
        if state.descent > 0:
            return  # The descent goes through the constraints on purpose.
        # The last iterations: at most a quarter of the run.
        window = min(settings.restoration_iterations, settings.max_iter // 4)
        near_end = state.iteration >= settings.max_iter - window
        if settings.max_evaluations and state.iteration:
            rate = state.evaluations / state.iteration
            left = settings.max_evaluations - state.evaluations
            window = min(
                settings.restoration_iterations,
                int(settings.max_evaluations / rate) // 4,
            )
            near_end = near_end or left <= window * rate
        self._near_end = near_end
        if not settings.restoration_iterations:
            state.restoration = 0
            return
        if near_end:
            # The last iterations shrink their moves, feasible or not: a full
            # move would leave the constraints with no time to come back.
            state.restoration = min(
                state.restoration + 1, settings.restoration_iterations
            )
            return
        if self._feasible():
            state.restoration = 0
            return
        if state.restoration >= settings.restoration_iterations:
            state.restoration = 0  # Given up; may start again once settled.
            return
        stall = settings.kkt_stall_iterations
        recent = state.history[-stall - 1 :]
        settled = len(state.history) > stall and (
            max(recent) - min(recent)
            <= RESTORE_SETTLED * max(abs(state.objective), 1e-300)
        )
        if state.restoration or settled:
            state.restoration += 1

    def _active_settings(self) -> Settings:
        """The settings of the iteration: tighter while restoring feasibility."""
        settings, restoration = self.settings, self.state.restoration
        if self.state.descent > 0:
            return replace(
                settings, elastic_cost=settings.elastic_cost * DESCENT_ELASTIC
            )
        if not restoration:
            return settings
        return replace(
            settings,
            move_limit=max(
                settings.move_limit * RESTORE_SHRINK**restoration, RESTORE_MIN_MOVE
            ),
            elastic_cost=settings.elastic_cost * RESTORE_ELASTIC,
        )

    def _remember_if_best(self) -> None:
        """Keep the point if it is feasible and the best so far."""
        state = self.state
        if self._feasible() and state.objective < state.best_objective:
            state.best_x = state.x.copy()
            state.best_objective = state.objective
            state.best_max_constraint = self._max_constraint()
            state.best_iteration = state.iteration

    def _no_progress(self) -> bool:
        """Whether the best KKT residual has stopped decreasing.

        Not by 10 % over the last ``kkt_stall_iterations`` iterations (since a
        switch to GCMMA, if any).
        """
        state = self.state
        window = self.settings.kkt_stall_iterations
        history = state.kkt_history[max(state.gcmma_since, 0) :]
        if len(history) <= window:
            return False
        return min(history[-window:]) >= STALL_DECREASE * min(history[:-window])

    def _moving(self) -> bool:
        """Whether a variable moved more than ``STALL_STEP`` lately."""
        window = self.settings.kkt_stall_iterations
        return max(self.state.step_history[-window:], default=np.inf) > STALL_STEP

    def _switch_if_cycling(self) -> None:
        """Switch MMA to GCMMA when it cycles.

        No progress while the iterates still move: MMA's approximations are too
        flat to settle; GCMMA's conservative ones are not.
        """
        if self.method == "mma" and self._no_progress() and self._moving():
            self.state.gcmma_since = self.state.iteration

    def _stalled(self) -> bool:
        """Whether the KKT residual stopped decreasing; say so if it did."""
        state, settings = self.state, self.settings
        window = settings.kkt_stall_iterations
        history = state.kkt_history
        if not self._no_progress() or self._moving():
            return False
        state.status = "stalled"
        state.message = (
            f"The KKT residual stalled at {min(history):.1e} over {window} "
            f"iterations, short of {settings.kkt_tolerance:g}: the precision "
            "this problem reaches."
        )
        return True

    def _solve(
        self,
        approximation: Approximation,
        scales: Array,
        start: Array,
        tolerance: float,
        settings: Settings,
    ) -> SubproblemSolution:
        """Solve a subproblem whose constraints are divided by their ``scales``.

        Args:
            approximation: The subproblem, its constraints divided.
            scales: The scales of its constraints.
            start: The multipliers to start from, of the constraints unscaled.
            tolerance: That of the dual, raised to the finest one.
            settings: The settings of the iteration.

        Returns:
            The solution, its multipliers and elastic variables those of the
            constraints unscaled.
        """
        # The feasibility tolerances in the units of the subproblem.
        finest = min(
            settings.dual_tolerance,
            ADAPTIVE_DUAL_FACTOR
            * min(settings.ineq_tolerance, settings.eq_tolerance)
            / float(np.max(scales, initial=1.0)),
        )
        tolerance = max(tolerance, finest)
        cost, quadratic = settings.elastic_cost, settings.elastic_quadratic
        solver = settings.dual_solver
        if solver == "auto":
            constraints = approximation.size
            variables = approximation.x.size
            work = variables * constraints**2
            few = constraints <= FEW_CONSTRAINTS and variables >= MANY_VARIABLES
            small = 0 < constraints <= settings.dense_dual_threshold
            if small and not few and work <= INTERIOR_POINT_WORK:
                solver = "interior_point"
            elif few:
                solver = "lbfgsb"
            else:
                solver = "newton" if _sparse(approximation.rows) else "lbfgsb"
        if solver == "interior_point" and approximation.size:
            solution = checked(
                approximation,
                solve_interior_point(approximation, cost, quadratic),
                cost,
                quadratic,
                tolerance,
            )
        else:
            solve = solve_newton if solver == "newton" else solve_dual
            solution = solve(approximation, cost, quadratic, start * scales, tolerance)
        return SubproblemSolution(
            solution.x, solution.multipliers / scales, solution.elastic * scales
        )

    @staticmethod
    def _tighten(
        approximation: Approximation, x: Array, objective: float, constraints: Array
    ) -> bool:
        """GCMMA: raise the curvature of the approximations below their function.

        Returns:
            Whether an approximation was not conservative at ``x``.
        """
        gap = objective - approximation.objective_value(x)
        gaps = constraints - approximation.constraint_values(x)
        low_objective = gap > CONSERVATIVE_TOLERANCE * (1 + abs(objective))
        low = gaps > CONSERVATIVE_TOLERANCE * (1 + np.abs(constraints))
        if not (low_objective or low.any()):
            return False
        weight = approximation.conservative_weight(x)
        if weight <= 0:
            return False
        objective_rho = approximation.objective_rho
        if low_objective:
            objective_rho = min(
                1.1 * (objective_rho + gap / weight), 10 * objective_rho
            )
        rho = approximation.constraint_rho.copy()
        rho[low] = np.minimum(1.1 * (rho[low] + gaps[low] / weight), 10 * rho[low])
        approximation.set_rho(objective_rho, rho)
        return True

    def _kkt_residual(self, gradient: Array, iteration: _Iteration) -> float:
        """Stationarity and complementarity at the iterate.

        With the rows of the working set and the multipliers of the last
        subproblem (whose active constraints are all in the working set),
        relative to the largest term of the gradient of the Lagrangian — of the
        objective, or of a constraint times its multiplier — whatever their
        units: a residual of 1e-3 means the same on every problem. Relative to
        the gradient of the objective alone, it read 10 to 10⁶ on a volume
        minimized under stresses: a volume fraction has a gradient of 1/n per
        variable, the stresses of order 1.
        """
        state, problem = self.state, self.problem
        # The multipliers of the subproblem are those of the objective on a
        # scale of 1.
        multipliers = state.objective_scale * iteration.multipliers
        lagrangian = gradient + times_rows(multipliers, iteration.rows)
        tolerance = BOUND_TOLERANCE * self.ranges
        at_lower = state.x <= problem.lower + tolerance
        at_upper = state.x >= problem.upper - tolerance
        projected = np.where(
            at_lower,
            np.minimum(lagrangian, 0.0),
            np.where(at_upper, np.maximum(lagrangian, 0.0), lagrangian),
        )
        constraint_terms = times_rows(np.abs(multipliers), abs(iteration.rows))
        scale = max(
            float(np.max(np.abs(gradient), initial=0.0)),
            float(np.max(constraint_terms, initial=0.0)),
            KKT_SCALE_FLOOR * state.gradient_scale,
        )
        complementarity = float(
            np.max(np.abs(multipliers * iteration.values), initial=0.0)
        )
        self.stationarity = projected
        down = state.x - problem.lower
        up = problem.upper - state.x
        near = np.flatnonzero(np.minimum(down, up) <= NEAR_BOUND * self.ranges)
        if near.size:
            # What the Lagrangian gains, per unit, when a variable goes toward
            # its nearest bound: positive where the bound holds.
            lower = down[near] <= up[near]
            costs = np.where(lower, lagrangian[near], -lagrangian[near]) / scale
            distances = np.minimum(down[near], up[near]) / self.ranges[near]
            cheapest = np.argsort(costs)[:BOUND_COSTS]
            self._bounds = (
                int(np.count_nonzero(at_lower | at_upper)),
                int(near.size),
                tuple(
                    (int(near[k]), float(costs[k]), float(distances[k]))
                    for k in cheapest
                ),
            )
        else:
            self._bounds = (0, 0, ())
        stationarity = float(np.max(np.abs(projected), initial=0.0))
        return max(stationarity, complementarity) / scale

    def _feasible(self) -> bool:
        state, settings = self.state, self.settings
        inequalities = state.constraints.max(initial=-np.inf) <= settings.ineq_tolerance
        equalities = np.abs(state.equalities).max(initial=0.0) <= settings.eq_tolerance
        return bool(inequalities and equalities)

    def _max_constraint(self) -> float:
        """The largest inequality value or equality violation."""
        state = self.state
        return float(
            max(
                state.constraints.max(initial=-np.inf),
                np.abs(state.equalities).max(initial=-np.inf),
            )
        )

    def _accept(
        self,
        solution: SubproblemSolution,
        iteration: _Iteration,
        objective: float,
        constraints: Array,
        equalities: Array,
        lower_asymptote: Array,
        upper_asymptote: Array,
    ) -> None:
        state = self.state
        change = abs(objective - state.objective)
        size = iteration.working_set.size
        state.x_before = state.x_previous
        state.x_previous = state.x
        state.x = solution.x
        state.lower_asymptote = lower_asymptote
        state.upper_asymptote = upper_asymptote
        state.multipliers = np.zeros(constraints.size)
        state.multipliers[iteration.working_set] = solution.multipliers[:size]
        state.equality_multipliers = solution.multipliers[size:]
        state.constraints_previous = state.constraints
        state.constraints = constraints
        state.equalities = equalities
        state.working_set = iteration.working_set
        state.objective = objective
        state.iteration += 1
        state.history.append(objective)
        settings = self.settings
        # Half the tolerance: room for what the dual leaves of the violation.
        state.equality_band = max(
            0.5 * settings.eq_tolerance,
            state.equality_band * settings.equality_band_decrease,
        )
        small = change <= settings.ftol_rel * max(abs(objective), 1e-300)
        state.objective_stall = state.objective_stall + 1 if small else 0
        self.cache.keep(iteration.working_set)

    def _check_stop(self, step: float) -> None:
        state, settings = self.state, self.settings
        state.x_stall = state.x_stall + 1 if step <= settings.xtol_rel else 0
        feasible = self._feasible()
        if (
            settings.ftol_rel
            and feasible
            and state.objective_stall >= settings.stall_iterations
        ):
            state.status = "ftol"
            state.message = (
                f"The objective changed less than {settings.ftol_rel:g} "
                f"over {settings.stall_iterations} iterations."
            )
        elif (
            settings.xtol_rel
            and feasible
            and state.x_stall >= settings.stall_iterations
        ):
            state.status = "xtol"
            state.message = (
                f"The point moved less than {settings.xtol_rel:g} "
                f"over {settings.stall_iterations} iterations."
            )
        elif state.iteration >= settings.max_iter:
            state.status = "max_iter"
            state.message = f"{settings.max_iter} iterations reached."
        elif (
            settings.max_row_evaluations
            and state.row_evaluations >= settings.max_row_evaluations
        ):
            state.status = "max_rows"
            state.message = (
                f"{state.row_evaluations} constraint gradients asked for, of a "
                f"budget of {settings.max_row_evaluations}."
            )

    def _report(
        self,
        step: float,
        inner: int,
        repairs: int,
        kkt: float,
        iteration: _Iteration,
        start: float,
    ) -> Report:
        state = self.state
        tolerance = self.settings.ineq_tolerance
        if state.lower_asymptote is not None and state.upper_asymptote is not None:
            widths = (state.upper_asymptote - state.lower_asymptote) / self.ranges
            spread = (
                float(widths.min()),
                float(np.median(widths)),
                float(widths.max()),
            )
        else:
            spread = (0.0, 0.0, 0.0)
        return Report(
            iteration=state.iteration,
            objective=state.objective,
            max_constraint=self._max_constraint(),
            violated=int(np.sum(state.constraints > tolerance)),
            active=int(np.sum(state.constraints >= -tolerance)),
            working_set=int(iteration.working_set.size),
            rows_computed=self._rows_computed,
            rows_reused=self._rows_reused,
            screening_repairs=repairs,
            inner_iterations=inner,
            kkt_residual=kkt,
            step=step,
            asymptote_spread=spread,
            model_time=self._model_time,
            optimizer_time=time.perf_counter() - start - self._model_time,
            method=self.method,
            status=state.status,
            directional_derivatives=self._products,
            restoration=state.restoration,
            descent=max(state.descent, 0),
            at_bound=self._bounds[0],
            near_bound=self._bounds[1],
            bound_costs=self._bounds[2],
        )


def _row_scales(rows: Rows, ranges: Array) -> Array:
    """The largest change of each constraint when one variable crosses its range.

    Rows independent of the variables get the smallest scale of the others.
    """
    if not rows.shape[0]:
        return np.ones(0)
    if is_sparse(rows):
        scaled = abs(rows).multiply(ranges[None, :]).tocsr()
        scales = np.asarray(scaled.max(axis=1).toarray(), dtype=float).ravel()
    else:
        scales = np.max(np.abs(rows) * ranges, axis=1).astype(float)
    positive = scales[scales > 0]
    floor = float(positive.min()) if positive.size else 1.0
    return np.asarray(np.maximum(scales, floor), dtype=float)


def _tightened(values: Array, inequalities: int, margin: float) -> Array:
    """The values of a subproblem, its inequality constraints tightened.

    The equality pairs, whose band may be narrower than the margin, are not.
    """
    if not margin:
        return values
    tightened = values.copy()
    tightened[:inequalities] += margin
    return tightened


def _divide_rows(rows: Rows, scales: Array) -> Rows:
    """The rows divided by their scales, in their precision."""
    if is_sparse(rows):
        divided: Rows = (sparse.diags(1.0 / scales) @ rows).astype(rows.dtype)
        return divided
    return np.asarray(rows / scales[:, None], dtype=rows.dtype)


SPARSE_SHARE = 0.1
"""Rows holding at most this share of nonzero entries are sparse for the dual:
the Hessian of Newton's method costs the square of their nonzeros."""


def _sparse(rows: Rows) -> bool:
    """Whether rows are sparse, in their format and in fact."""
    if not is_sparse(rows):
        return False
    total = rows.shape[0] * rows.shape[1]
    return bool(total == 0 or rows.nnz <= SPARSE_SHARE * total)


def _merge(colored: sparse.csr_matrix, exact: Rows, where: NDArray[np.bool_]) -> Rows:
    """The colored rows, with the exact ones where asked for, in order.

    Dense when the exact rows are: a sparse matrix of dense rows costs its
    indices in memory, and would be taken for sparse by the dual (spec § 3.7).
    """
    if not is_sparse(exact):
        merged = colored.toarray()
        merged[where] = exact
        return merged
    positions = np.concatenate([np.flatnonzero(where), np.flatnonzero(~where)])
    stacked = sparse.vstack(
        [sparse.csr_matrix(exact, dtype=colored.dtype), colored[~where]], format="csr"
    )
    return stacked[np.argsort(positions)]
