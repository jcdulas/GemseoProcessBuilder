"""Events worth calling Claude for, found without calling it (spec § 4.2).

Each detector is a pure function of a history: it says whether the run shows
its symptom now. The pilot decides when to report them.

An algorithm reporting its outer iterations (``LSO_MMA``, ``LSO_GCMMA``: the
``algorithm_state`` of the problem) has its own detectors (spec § 8 of the
large-scale optimizer): screening repairs at every iteration, a working set
that churns, asymptotes that narrow, many GCMMA inner iterations, stale rows
that cost repairs, a budget of rows running out; and a run stuck — its KKT
residual no longer decreasing far from convergence, or its constraints violated
for long — when the design itself is to be looked at (spec § 4.8).
"""

from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from gemseo_claude_pilot.snapshots import HistorySnapshot
from gemseo_claude_pilot.snapshots import ProblemSnapshot

EventKind = Literal[
    "stagnation",
    "infeasibility",
    "divergence",
    "failed_evaluations",
    "oscillation",
    "bounds",
    "repairs",
    "churn",
    "asymptotes",
    "inner_iterations",
    "stale_rows",
    "row_budget",
    "stuck",
    "plateau",
    "frozen",
]


@dataclass(frozen=True)
class Event:
    """A symptom of the run, at the evaluation where it was seen."""

    kind: EventKind
    message: str
    index: int


@dataclass(frozen=True)
class DetectorSettings:
    """The thresholds of the detectors."""

    stagnation_window: int = 20
    """Evaluations without a relative improvement of the best feasible objective..."""

    stagnation_tolerance: float = 1e-4
    """...larger than this."""

    infeasibility_window: int = 30
    """Evaluations without a feasible point."""

    divergence_window: int = 10
    """Evaluations over which the objective or the violation keeps growing."""

    oscillation_window: int = 6
    """Last points whose moves go back and forth with a shrinking step."""

    bounds_share: float = 0.5
    """Share of the design components at a bound beyond which it is reported."""

    bounds_tolerance: float = 1e-6
    """Normalized distance to a bound under which a component is at it."""

    algorithm_window: int = 5
    """Outer iterations an algorithm's detector looks at."""

    churn_share: float = 0.3
    """The working set changes more than this share of its size, on average."""

    narrow_asymptotes: float = 0.02
    """The median distance between asymptotes, as a share of the ranges, below
    which the moves are too small to converge in time."""

    many_inner: float = 5.0
    """GCMMA inner iterations per outer iteration, on average."""

    row_budget_share: float = 0.8
    """The share of the budget of rows spent beyond which it is reported."""

    stuck_window: int = 20
    """Outer iterations over which a stuck run is recognized..."""

    stuck_factor: float = 10.0
    """...its best KKT residual still above this many times its tolerance."""

    plateau_window: int = 10
    """Outer iterations over which the objective of a plateau..."""

    plateau_tolerance: float = 0.005
    """...improved by less than this share."""

    settling_factor: float = 100.0
    """A run settles when its KKT residual is below this many times its
    tolerance: the bounds it holds are then the ones it will keep."""


def detect(
    history: HistorySnapshot,
    problem: ProblemSnapshot,
    settings: DetectorSettings | None = None,
    since: int = 0,
) -> list[Event]:
    """The symptoms the run shows now.

    Args:
        history: The evaluations so far.
        problem: The problem.
        settings: The thresholds of the detectors.
        since: The first evaluation whose failures are reported; earlier ones
            were reported before.
    """
    settings = settings or DetectorSettings()
    events = [
        stagnation(history, settings),
        infeasibility(history, settings),
        divergence(history, settings),
        failed_evaluations(history, since),
        oscillation(history, settings),
        bounds(history, problem, settings),
        *algorithm_events(problem, settings, history.n_evaluations - 1),
    ]
    return [event for event in events if event is not None]


def algorithm_events(
    problem: ProblemSnapshot, settings: DetectorSettings, index: int
) -> list[Event]:
    """The symptoms of the outer iterations of the large-scale optimizer."""
    reports = problem.algorithm_state
    window = settings.algorithm_window
    if len(reports) < window:
        return []
    last = reports[-window:]
    events: list[Event] = []

    def add(kind: EventKind, message: str) -> None:
        events.append(Event(kind, message, index))

    if all(report["screening_repairs"] > 0 for report in last):
        add(
            "repairs",
            f"A screened-out constraint was violated at each of the last {window} "
            "outer iterations: the subproblem is solved again each time; a wider "
            "screening margin would take these constraints in at once.",
        )
    sizes = np.array([report["working_set"] for report in last], dtype=float)
    changes = np.abs(np.diff(sizes)) / np.maximum(sizes[:-1], 1)
    if changes.mean() > settings.churn_share:
        add(
            "churn",
            f"The working set changes by {changes.mean():.0%} of its size per "
            "iteration: rows are computed for constraints that leave it at once; "
            "a larger keep_factor would hold them.",
        )
    spreads = [report.get("asymptote_spread") for report in last]
    medians = [spread[1] for spread in spreads if spread]
    if medians and medians[-1] < settings.narrow_asymptotes:
        add(
            "asymptotes",
            f"The asymptotes narrowed to {medians[-1]:.1%} of the ranges (median): "
            "the variables oscillated and the moves are now tiny; a larger "
            "asymptote_decrease narrows them less.",
        )
    inner = np.mean([report["inner_iterations"] for report in last])
    if inner >= settings.many_inner:
        add(
            "inner_iterations",
            f"GCMMA needs {inner:.1f} inner iterations per outer iteration: its "
            "approximations are too flat; each costs an evaluation.",
        )
    reused = sum(report["rows_reused"] for report in last)
    repairs = sum(report["screening_repairs"] for report in last)
    if reused and repairs >= window // 2:
        add(
            "stale_rows",
            f"{reused} rows were reused over the last {window} iterations while "
            f"the step was repaired {repairs} times: stale rows may mislead the "
            "subproblem; row_refresh always computes them again.",
        )
    stuck = _stuck(problem, reports, settings)
    if stuck:
        add("stuck", stuck)
    plateau = _plateau(reports, settings)
    if plateau:
        add("plateau", plateau)
    frozen = _frozen(problem, reports, settings)
    if frozen:
        add("frozen", frozen)
    budget = problem.settings.get("max_row_evaluations") or 0
    spent = sum(report["rows_computed"] for report in reports)
    if budget and spent >= settings.row_budget_share * budget:
        add(
            "row_budget",
            f"{spent} constraint gradients of a budget of {budget} are spent.",
        )
    return events


def _stuck(
    problem: ProblemSnapshot,
    reports: Sequence[Mapping[str, Any]],
    settings: DetectorSettings,
) -> str:
    """Why the run is stuck, or nothing.

    Its best KKT residual has not decreased by 10 % over the window while still
    far from its tolerance, or its constraints stayed violated over the window.
    """
    window = settings.stuck_window
    if len(reports) <= window:
        return ""
    residuals = [float(report["kkt_residual"]) for report in reports]
    best_before = min(residuals[:-window])
    best = min(residuals)
    tolerance = float(problem.settings.get("kkt_tolerance") or 1e-3)
    if best > 0.9 * best_before and best > settings.stuck_factor * tolerance:
        return (
            f"The best KKT residual, {best:.2g}, has not decreased by 10 % over "
            f"the last {window} outer iterations, far from its tolerance "
            f"{tolerance:g}: settings will not unblock it; look at the design "
            "(its load path, hot spots, gray or dead material) and consider a "
            "restart from a better one."
        )
    tolerance = problem.inequality_tolerance
    violations = [float(report["max_constraint"]) for report in reports]
    recent, before = violations[-window:], violations[:-window]
    # Slightly infeasible iterates are normal while MMA descends: only a
    # violation that no longer decreases is a symptom.
    if min(recent) > tolerance and min(recent) > 0.5 * min(before):
        return (
            f"The constraints stayed violated over the last {window} outer "
            f"iterations, the violation no longer decreasing (at least "
            f"{min(recent):.2g}): look at the design (where the constraints are "
            "violated, whether the load reaches the supports) and consider a "
            "restart."
        )
    return ""


def _frozen(
    problem: ProblemSnapshot,
    reports: Sequence[Mapping[str, Any]],
    settings: DetectorSettings,
) -> str:
    """Variables at or near a bound as the run settles, or nothing.

    The optimizer converges to a local optimum: a bound reached early, while
    the design was far from the optimum, is a decision it cannot question.
    """
    last = reports[-1]
    tolerance = float(problem.settings.get("kkt_tolerance") or 1e-3)
    costs = last.get("bound_costs") or []
    if (
        not last.get("near_bound")
        or not costs
        or float(last["kkt_residual"]) > settings.settling_factor * tolerance
    ):
        return ""
    cheapest = ", ".join(
        f"{index} (cost {cost:.2g}, {distance:.1%} from its bound)"
        for index, cost, distance in costs
    )
    return (
        f"The run is settling (KKT residual {float(last['kkt_residual']):.2g}, "
        f"tolerance {tolerance:g}) with {last['near_bound']} variable(s) at or "
        f"within 1 % of a bound ({last['at_bound']} at it). The cheapest to move "
        f"toward or away from it, by component index: {cheapest}. A bound taken "
        "early is a decision the optimizer cannot question: the optimum may be "
        "local."
    )


def _plateau(reports: Sequence[Mapping[str, Any]], settings: DetectorSettings) -> str:
    """The objective no longer improves, or nothing."""
    window = settings.plateau_window
    if len(reports) <= window:
        return ""
    objectives = [float(report["objective"]) for report in reports]
    before = min(objectives[:-window])
    now = min(objectives)
    gain = (before - now) / max(abs(before), 1e-300)
    if gain >= settings.plateau_tolerance:
        return ""
    last = reports[-1]
    return (
        f"The objective improved by {gain:.2%} over the last {window} outer "
        f"iterations (best {now:.6g}); the maximum constraint is "
        f"{float(last['max_constraint']):.3g} and the KKT residual "
        f"{float(last['kkt_residual']):.2g}. Each iteration costs rows and "
        "time for little gain: stop the run if the design is acceptable, "
        "restart it if the design is at fault, or say what the next iterations "
        "should still bring."
    )


def stagnation(history: HistorySnapshot, settings: DetectorSettings) -> Event | None:
    """The best feasible objective has not improved over the window."""
    window = settings.stagnation_window
    n = history.n_evaluations
    objective = np.where(history.feasible, history.standardized_objective, np.inf)
    if n <= window or not np.isfinite(objective[: n - window]).any():
        return None
    before = float(objective[: n - window].min())
    now = float(objective.min())
    if before - now > settings.stagnation_tolerance * max(abs(before), 1.0):
        return None
    return Event(
        "stagnation",
        f"The best feasible objective has not improved by more than a relative "
        f"{settings.stagnation_tolerance:g} over the last {window} evaluations.",
        n - 1,
    )


def infeasibility(history: HistorySnapshot, settings: DetectorSettings) -> Event | None:
    """No feasible point over the window."""
    window = settings.infeasibility_window
    n = history.n_evaluations
    if n < window or history.feasible[-window:].any():
        return None
    violation = history.violation[-window:]
    measured = violation[np.isfinite(violation)]
    least = f"; the smallest violation is {measured.min():.3g}" if measured.size else ""
    return Event(
        "infeasibility",
        f"No feasible point in the last {window} evaluations{least}.",
        n - 1,
    )


def divergence(history: HistorySnapshot, settings: DetectorSettings) -> Event | None:
    """The objective or the constraint violation keeps growing."""
    window = settings.divergence_window
    n = history.n_evaluations
    if n < window:
        return None
    objective = history.standardized_objective[-window:]
    violation = history.violation[-window:]
    if _growing(objective[np.isfinite(objective)], window):
        what = "objective"
    elif violation[-1] > 0 and _growing(violation, window):
        what = "constraint violation"
    else:
        return None
    return Event(
        "divergence",
        f"The {what} has kept growing over the last {window} evaluations.",
        n - 1,
    )


def failed_evaluations(history: HistorySnapshot, since: int = 0) -> Event | None:
    """Evaluations that raised, or returned NaN or infinite values."""
    failed = np.flatnonzero(history.failed[since:]) + since
    if not failed.size:
        return None
    first = ", ".join(str(index) for index in failed[:5])
    more = "…" if failed.size > 5 else ""
    return Event(
        "failed_evaluations",
        f"{failed.size} evaluation(s) failed or returned values that are not "
        f"finite (evaluations {first}{more}).",
        int(failed[-1]),
    )


def oscillation(history: HistorySnapshot, settings: DetectorSettings) -> Event | None:
    """The last moves go back and forth with a shrinking step."""
    points = history.recent_x[-settings.oscillation_window :]
    if len(points) < settings.oscillation_window:
        return None
    moves = np.diff(points, axis=0)
    lengths = np.linalg.norm(moves, axis=1)
    if not (lengths > 0).all():
        return None
    cosines = np.sum(moves[1:] * moves[:-1], axis=1) / (lengths[1:] * lengths[:-1])
    back_and_forth = np.count_nonzero(cosines < -0.5)
    if back_and_forth < 0.75 * len(cosines) or lengths[-1] >= lengths[0]:
        return None
    return Event(
        "oscillation",
        f"The design point goes back and forth over the last "
        f"{settings.oscillation_window} evaluations, with a shrinking step.",
        history.n_evaluations - 1,
    )


def bounds(
    history: HistorySnapshot, problem: ProblemSnapshot, settings: DetectorSettings
) -> Event | None:
    """Many design components are at one of their bounds."""
    if not len(history.recent_x):
        return None
    last = history.recent_x[-1]
    lower, upper = problem.lower_bounds, problem.upper_bounds
    bounded = np.isfinite(lower) & np.isfinite(upper) & (upper > lower)
    tolerance = settings.bounds_tolerance
    at_bound = bounded & ((last <= tolerance) | (last >= 1 - tolerance))
    share = np.count_nonzero(at_bound) / max(last.size, 1)
    if share <= settings.bounds_share:
        return None
    return Event(
        "bounds",
        f"{share:.0%} of the design components are at one of their bounds.",
        history.n_evaluations - 1,
    )


def _growing(values: NDArray[np.float64], window: int) -> bool:
    """Whether the values rise at almost every step, over most of the window."""
    if len(values) < 0.8 * window:
        return False
    rises = np.count_nonzero(np.diff(values) > 0)
    return bool(values[-1] > values[0] and rises >= 0.8 * (len(values) - 1))
