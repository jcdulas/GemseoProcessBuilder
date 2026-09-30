"""The context of a call to Claude (spec § 6.1).

A JSON document: the problem, the state of the run, its history compressed
(the last evaluations in full, earlier ones as statistics per window), the
events, the decisions already taken and the question of the user. Large design
spaces are summarized per variable, with their most important components.
The document is filtered by the data level (spec § 7.1) and kept near a target
size by merging the history windows.
"""

import json
from collections.abc import Callable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.design import DesignView
from gemseo_claude_pilot.detectors import Event
from gemseo_claude_pilot.privacy import Anonymizer
from gemseo_claude_pilot.privacy import DataLevel
from gemseo_claude_pilot.snapshots import Array
from gemseo_claude_pilot.snapshots import Constraint
from gemseo_claude_pilot.snapshots import HistorySnapshot
from gemseo_claude_pilot.snapshots import ProblemSnapshot
from gemseo_claude_pilot.snapshots import Variable
from gemseo_claude_pilot.snapshots import normalization

TriggerKind = Literal["periodic", "event", "question", "start", "end", "report"]

TARGET_TOKENS = 8_000
"""The size a context should stay under."""

RECENT_EVALUATIONS = 20
"""The last evaluations given in full."""

WINDOW = 20
"""The number of earlier evaluations summarized together, at first."""

LISTED_VARIABLE_SIZE = 10
"""Variables up to this size are given component by component..."""

LISTED_DESIGN_SIZE = 200
"""...when the design vector has at most this many components."""

IMPORTANT_COMPONENTS = 20

LISTED_CONSTRAINT_SIZE = 10
"""Constraints of more components are summarized at the best point."""

LARGEST_COMPONENTS = 10
"""The components of a summarized constraint listed, the largest first."""

RECENT_REPORTS = 10
"""The reports of an algorithm's outer iterations sent in full..."""

REPORT_WINDOW = 20
"""...earlier ones summarized per window of this many."""
"""The components of summarized variables given one by one."""


@dataclass(frozen=True)
class PastDecision:
    """A decision already taken, and what followed."""

    evaluation: int
    decision: Decision
    outcome: str = ""


def estimate_tokens(text: str) -> int:
    """A rough number of tokens: four characters each."""
    return len(text) // 4 + 1


def render(context: dict[str, Any]) -> str:
    """The context as the text sent to Claude."""
    return json.dumps(context, ensure_ascii=False)


def build_context(
    problem: ProblemSnapshot,
    history: HistorySnapshot,
    trigger: TriggerKind = "periodic",
    events: Sequence[Event] = (),
    decisions: Sequence[PastDecision] = (),
    question: str = "",
    level: DataLevel = "no_code",
    anonymizer: Anonymizer | None = None,
    target_tokens: int = TARGET_TOKENS,
    pilot: Mapping[str, Any] | None = None,
    design: DesignView | None = None,
    design_detail: bool = False,
) -> dict[str, Any]:
    """The context of a call.

    Args:
        problem: The problem as it is now.
        history: Its evaluations so far.
        trigger: Why Claude is called.
        events: The events found since the last call.
        decisions: The decisions already taken.
        question: The question of the user, if any.
        level: What may be sent.
        anonymizer: The anonymizer of the run, kept from one call to the
            next; required in ``anonymized``.
        target_tokens: The size the context should stay under.
        pilot: What the pilot may do now: its mode, the allowed actions,
            the current segment.
        design: The design, when the model describes its physics (spec
            § 4.8), whatever the data level.
        design_detail: Whether to give its indicators and maps.

    Raises:
        ValueError: When the level is ``anonymized`` without an anonymizer.
    """
    states = constraint_states(problem, history)
    vectors = dict(history.best_constraints)
    hide: Callable[[str], str] = str
    if level == "anonymized":
        if anonymizer is None:
            raise ValueError("The anonymized level needs the anonymizer of the run.")
        history = anonymizer.history(history, problem)
        problem = anonymizer.problem(problem)
        states = {anonymizer.name(name): state for name, state in states.items()}
        vectors = {anonymizer.name(name): values for name, values in vectors.items()}
        question = anonymizer.conceal(question)
        hide = anonymizer.conceal

    fixed: dict[str, Any] = {
        "trigger": trigger,
        "pilot": dict(pilot or {}),
        "problem": _problem(problem, history, states, vectors, level, hide),
        "state": _state(problem, history),
        "events": [
            {
                "kind": event.kind,
                "evaluation": event.index,
                "message": hide(event.message),
            }
            for event in events
        ],
        "decisions": [_past_decision(item, level, hide) for item in decisions],
    }
    if problem.algorithm_state:
        fixed["optimizer"] = optimizer_state(problem.algorithm_state, level)
    if design is not None:
        fixed["design"] = design.context(design_detail)
    if question:
        fixed["question"] = question
    recent, window = RECENT_EVALUATIONS, WINDOW
    while True:
        context = {**fixed, "history": _history(history, recent, window)}
        earlier = history.n_evaluations - recent
        if estimate_tokens(render(context)) <= target_tokens:
            return context
        if earlier > window:
            window *= 2
        elif recent > 5:
            recent //= 2
        else:
            return context


def _past_decision(
    item: PastDecision, level: DataLevel, hide: Callable[[str], str]
) -> dict[str, Any]:
    """A decision already taken; in ``anonymized``, without its real values."""
    decision = item.decision
    if level == "anonymized":
        content: dict[str, Any] = {
            "diagnosis": hide(decision.diagnosis),
            "action": {"kind": decision.action.kind},
            "rationale": hide(decision.rationale),
        }
    else:
        content = decision.model_dump(mode="json", exclude_defaults=True)
        # The kind of an action is its default: kept, or Claude would not know it.
        content["action"] = decision.action.model_dump(mode="json")
    return {
        "evaluation": item.evaluation,
        "decision": content,
        "outcome": hide(item.outcome),
    }


def _problem(
    problem: ProblemSnapshot,
    history: HistorySnapshot,
    states: dict[str, str],
    vectors: Mapping[str, Array],
    level: DataLevel,
    hide: Callable[[str], str],
) -> dict[str, Any]:
    best = history.best_index
    section: dict[str, Any] = {
        "driver": problem.driver_kind,
        "formulation": problem.formulation or None,
        "algorithm": {
            "name": problem.algo_name,
            "settings": json.loads(hide(json.dumps(_jsonable(dict(problem.settings))))),
        },
        "evaluation_budget": problem.evaluation_budget,
        "gradients": problem.gradients,
        "objective": {
            "name": problem.objective,
            "direction": "minimize" if problem.minimize else "maximize",
        },
        "constraints": [
            {
                "name": constraint.name,
                "type": constraint.type,
                "size": constraint.size,
                "value_at_best": _number(
                    history.constraints[constraint.name][best]
                    if best >= 0 and constraint.name in history.constraints
                    else np.nan
                ),
                "state_at_best": states.get(constraint.name, "unknown"),
                **_vector_summary(
                    vectors.get(constraint.name), constraint, problem, level
                ),
            }
            for constraint in problem.constraints
        ],
        "constraint_convention": (
            "Standardized values: an inequality holds when it is at most 0, an "
            "equality when it is 0, within the tolerances."
        ),
        "observables": list(problem.observables),
        "design_variables": [],
    }
    if level == "anonymized":
        section["design_space_convention"] = (
            "Design values are normalized to [0, 1] by the bounds the user set; "
            "the objective and the constraints are divided by a fixed scale."
        )
    else:
        section["tolerances"] = {
            "equality": problem.equality_tolerance,
            "inequality": problem.inequality_tolerance,
        }
        section["components"] = [
            {
                "name": component.name,
                "description": component.description,
                "inputs": list(component.inputs),
                "outputs": list(component.outputs),
            }
            for component in problem.components
        ]
    if problem.sub_scenarios:
        section["sub_scenarios"] = [
            {
                "name": sub.name,
                "algorithm": {
                    "name": sub.algo_name,
                    "settings": _jsonable(dict(sub.settings)),
                },
                "design_variables": list(sub.design_variables),
                "objective": sub.objective,
            }
            for sub in problem.sub_scenarios
        ]
    listed = problem.design_size <= LISTED_DESIGN_SIZE
    start = 0
    summarized: list[tuple[Variable, int]] = []
    for variable in problem.variables:
        stop = start + variable.size
        best_x = history.best_x[start:stop]
        if listed and variable.size <= LISTED_VARIABLE_SIZE:
            section["design_variables"].append(_listed(variable, best_x))
        else:
            section["design_variables"].append(_summary(variable, best_x))
            summarized.append((variable, start))
        start = stop
    if summarized:
        section["most_important_components"] = _important(summarized, history)
    return section


def _state(problem: ProblemSnapshot, history: HistorySnapshot) -> dict[str, Any]:
    n = history.n_evaluations
    best = history.best_index
    state: dict[str, Any] = {
        "evaluations": n,
        "evaluations_left": max(problem.evaluation_budget - n, 0),
        "failed_evaluations": int(history.failed.sum()),
        "feasible_evaluations": int(history.feasible.sum()),
    }
    if best >= 0:
        state["best"] = {
            "evaluation": best,
            "objective": _number(history.objective[best]),
            "feasible": bool(history.feasible[best]),
            "max_violation": _number(history.violation[best]),
        }
    return state


def _history(history: HistorySnapshot, recent: int, window: int) -> dict[str, Any]:
    n = history.n_evaluations
    first_recent = max(n - recent, 0)
    gradient = history.gradient_norm
    rows = []
    for index in range(first_recent, n):
        row: dict[str, Any] = {
            "evaluation": index,
            "objective": _number(history.objective[index]),
            "max_violation": _number(history.violation[index]),
            "step": _number(history.step[index]),
        }
        if gradient is not None and np.isfinite(gradient[index]):
            row["gradient_norm"] = _number(gradient[index])
        rows.append(row)
    earlier = []
    objective = history.standardized_objective
    sign = 1.0 if history.minimize else -1.0
    for start in range(0, first_recent, window):
        stop = min(start + window, first_recent)
        feasible = history.feasible[start:stop]
        valid = np.isfinite(objective[start:stop])
        earlier.append(
            {
                "evaluations": [start, stop - 1],
                "best_objective": _number(
                    sign * objective[start:stop][valid].min() if valid.any() else np.nan
                ),
                "smallest_violation": _smallest(history.violation[start:stop]),
                "feasible": int(feasible.sum()),
                "failed": int((~valid).sum()),
                "mean_step": _number(history.step[start:stop].mean()),
            }
        )
    return {"earlier": earlier, "recent": rows}


def _listed(variable: Variable, best_x: Array) -> dict[str, Any]:
    return {
        "name": variable.name,
        "size": variable.size,
        "integer": variable.integer,
        "lower": _numbers(variable.lower),
        "upper": _numbers(variable.upper),
        "current": None if variable.value is None else _numbers(variable.value),
        "best": _numbers(best_x),
    }


def _summary(variable: Variable, best_x: Array) -> dict[str, Any]:
    offset, scale = normalization(variable.lower, variable.upper)
    position = (best_x - offset) / scale
    bounded = scale != 1.0
    return {
        "name": variable.name,
        "size": variable.size,
        "integer": variable.integer,
        "lower": _range(variable.lower),
        "upper": _range(variable.upper),
        "best": _range(best_x),
        "share_at_lower_bound": _number(np.mean(bounded & (position <= 1e-6))),
        "share_at_upper_bound": _number(np.mean(bounded & (position >= 1 - 1e-6))),
    }


def _important(
    summarized: list[tuple[Variable, int]], history: HistorySnapshot
) -> list[dict[str, Any]]:
    """The components that matter most, as in the results filter (SPEC § 12.2).

    The largest gradients at the best point times the range of the variable;
    without gradient, the components that moved most since the first point.
    """
    candidates = []
    for variable, start in summarized:
        stop = start + variable.size
        _, scale = normalization(variable.lower, variable.upper)
        gradient = history.best_gradient
        if gradient is not None and gradient.size == history.best_x.size:
            importance = np.abs(gradient[start:stop]) * scale
            how = "gradient times range"
        else:
            importance = np.abs(
                history.best_x[start:stop] - history.first_x[start:stop]
            )
            importance /= scale
            how = "normalized move since the first point"
        count = min(IMPORTANT_COMPONENTS, variable.size)
        top = np.argpartition(-np.nan_to_num(importance, nan=-1.0), count - 1)[:count]
        candidates += [
            (float(importance[i]), variable, int(i), start, how) for i in top
        ]
    candidates.sort(key=lambda item: -np.nan_to_num(item[0], nan=-1.0))
    return [
        {
            "variable": variable.name,
            "index": i,
            "best": _number(history.best_x[start + i]),
            "lower": _number(variable.lower[i]),
            "upper": _number(variable.upper[i]),
            "importance": _number(importance),
            "ranked_by": how,
        }
        for importance, variable, i, start, how in candidates[:IMPORTANT_COMPONENTS]
    ]


def _vector_summary(
    values: Array | None,
    constraint: Constraint,
    problem: ProblemSnapshot,
    level: DataLevel,
) -> dict[str, Any]:
    """A constraint of many components at the best point, in a few numbers.

    Its size, the count and share of its violated and active components, and,
    but in ``anonymized``, the quantiles of its values and its largest
    components; ``get_constraint`` gives slices.
    """
    if values is None or constraint.size <= LISTED_CONSTRAINT_SIZE:
        return {}
    violated, active = component_states(values, constraint, problem)
    summary: dict[str, Any] = {
        "violated_components": int(violated.sum()),
        "active_components": int(active.sum()),
        "share_active": _number(active.mean()),
    }
    if level != "anonymized":
        summary["quantiles"] = dict(
            zip(
                ("min", "q10", "median", "q90", "max"),
                _numbers(np.asarray(np.quantile(values, [0, 0.1, 0.5, 0.9, 1]), float)),
                strict=True,
            )
        )
        largest = np.argsort(values)[::-1][:LARGEST_COMPONENTS]
        summary["largest_components"] = [
            [int(index), _number(values[index])] for index in largest
        ]
    return {"summary_at_best": summary}


def component_states(
    values: Array, constraint: Constraint, problem: ProblemSnapshot
) -> tuple[NDArray[np.bool_], NDArray[np.bool_]]:
    """Which components of a constraint are violated, and which are active."""
    if constraint.type == "eq":
        tolerance = problem.equality_tolerance
        violated = np.abs(values) > tolerance
        return violated, ~violated
    tolerance = problem.inequality_tolerance
    violated = values > tolerance
    return violated, (values >= -10 * tolerance) & ~violated


REPORT_FIELDS = (
    "iteration",
    "method",
    "objective",
    "max_constraint",
    "kkt_residual",
    "working_set",
    "rows_computed",
    "rows_reused",
    "screening_repairs",
    "inner_iterations",
    "step",
    "restoration",
    "directional_derivatives",
    "at_bound",
    "near_bound",
    "bound_costs",
)
"""What a report of an outer iteration tells Claude."""


def optimizer_state(
    reports: Sequence[Mapping[str, Any]], level: DataLevel = "no_code"
) -> dict[str, Any]:
    """The outer iterations of the optimizer: the last ones, then per window.

    The objective and the constraint of a report are left out in
    ``anonymized``: their scale would tell.
    """
    hidden = {"objective", "max_constraint"} if level == "anonymized" else set()
    fields = [name for name in REPORT_FIELDS if name not in hidden]

    def compact(report: Mapping[str, Any]) -> dict[str, Any]:
        row = {}
        for name in fields:
            value = report.get(name)
            if name == "bound_costs":
                value = [
                    [index, _number(cost), _number(distance)]
                    for index, cost, distance in value or []
                ]
                if not value:
                    continue
            row[name] = _number(value) if isinstance(value, float) else value
        spread = report.get("asymptote_spread")
        if spread:
            row["asymptote_median"] = _number(spread[1])
        return row

    recent = list(reports[-RECENT_REPORTS:])
    earlier = list(reports[: max(len(reports) - RECENT_REPORTS, 0)])
    windows = []
    for start in range(0, len(earlier), REPORT_WINDOW):
        window = earlier[start : start + REPORT_WINDOW]
        windows.append(
            {
                "iterations": [window[0]["iteration"], window[-1]["iteration"]],
                "mean_working_set": _number(
                    np.mean([item["working_set"] for item in window])
                ),
                "rows_computed": int(sum(item["rows_computed"] for item in window)),
                "screening_repairs": int(
                    sum(item["screening_repairs"] for item in window)
                ),
                "inner_iterations": int(
                    sum(item["inner_iterations"] for item in window)
                ),
            }
        )
    return {
        "note": "The evaluations of the history include the GCMMA inner "
        "iterations and the screening repairs: their steps and objectives are "
        "not those of the optimizer's iterations. Read its progress here.",
        "outer_iterations": len(reports),
        "rows_computed": int(sum(item["rows_computed"] for item in reports)),
        "recent": [compact(item) for item in recent],
        "earlier": windows,
    }


def constraint_states(
    problem: ProblemSnapshot, history: HistorySnapshot
) -> dict[str, str]:
    """Whether each constraint is violated, active or inactive at the best point."""
    best = history.best_index
    states = {}
    for constraint in problem.constraints:
        values = history.constraints.get(constraint.name)
        if best < 0 or values is None or not np.isfinite(values[best]):
            continue
        value = float(values[best])
        if constraint.type == "eq":
            tolerance = problem.equality_tolerance
            states[constraint.name] = "violated" if value > tolerance else "active"
        else:
            tolerance = problem.inequality_tolerance
            if value > tolerance:
                states[constraint.name] = "violated"
            elif value >= -10 * tolerance:
                states[constraint.name] = "active"
            else:
                states[constraint.name] = "inactive"
    return states


def _number(value: Any) -> float | None:
    number = float(value)
    return float(f"{number:.6g}") if np.isfinite(number) else None


def _smallest(values: Array) -> float | None:
    finite = values[np.isfinite(values)]
    return _number(finite.min()) if finite.size else None


def _numbers(values: Array) -> list[float | None]:
    return [_number(value) for value in values]


def _range(values: Array) -> dict[str, float | None]:
    finite = values[np.isfinite(values)]
    if not finite.size:
        return {"min": None, "max": None}
    return {"min": _number(finite.min()), "max": _number(finite.max())}


def _jsonable(value: Any) -> Any:
    """Settings as JSON: containers kept, other objects written as text."""
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, bool | int | str) or value is None:
        return value
    if isinstance(value, float):
        return _number(value)
    return str(value)
