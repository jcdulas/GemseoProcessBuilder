"""The limits every decision must respect, enforced in code (spec § 4.3).

Claude proposes; :func:`check` accepts, adjusts or rejects. An adjusted
decision comes with notes saying what changed; a rejected one raises
:class:`RejectedDecisionError`, whose message is meant to be sent back to Claude so
it can correct itself.
"""

from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from gemseo_claude_pilot.algorithms import AlgorithmInfo
from gemseo_claude_pilot.algorithms import gemseo_algorithms
from gemseo_claude_pilot.algorithms import incompatibilities
from gemseo_claude_pilot.algorithms import settings_errors
from gemseo_claude_pilot.decisions import ACTION_KINDS
from gemseo_claude_pilot.decisions import ActionKind
from gemseo_claude_pilot.decisions import AddSamples
from gemseo_claude_pilot.decisions import ChangeDesignSpace
from gemseo_claude_pilot.decisions import ChangeSettings
from gemseo_claude_pilot.decisions import ChangeSubScenario
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.decisions import Restart
from gemseo_claude_pilot.decisions import Steer
from gemseo_claude_pilot.decisions import SwitchAlgorithm
from gemseo_claude_pilot.decisions import Values
from gemseo_claude_pilot.decisions import VariableChange
from gemseo_claude_pilot.design import DesignView
from gemseo_claude_pilot.design import transform_errors
from gemseo_claude_pilot.snapshots import DRIVER_NAMES
from gemseo_claude_pilot.snapshots import Array
from gemseo_claude_pilot.snapshots import DriverKind
from gemseo_claude_pilot.snapshots import ProblemSnapshot
from gemseo_claude_pilot.snapshots import Variable

ACTIONS_OF_DRIVER: Mapping[DriverKind, frozenset[ActionKind]] = {
    "optimization": frozenset(
        {
            "none",
            "change_settings",
            "change_design_space",
            "switch_algorithm",
            "stop",
            "change_sub_scenario",
            "restart",
            "steer",
        }
    ),
    "doe": frozenset({"none", "add_samples", "stop"}),
}

MANAGED_SETTINGS = frozenset(
    {
        "callbacks",
        "enable_progress_bar",
        "jacobian_mode",
        "log_problem",
        "preprocessors",
        "progress_bar_data_name",
        "reset_iteration_counters",
        "sparsity_pattern",
        "store_jacobian",
        "use_database",
        "use_one_line_progress_bar",
    }
)
"""Settings the pilot owns: the history and the logs depend on them; and the
colored Jacobians of the LSO algorithms, which need a function of the user's
code (the sparsity pattern)."""


@dataclass(frozen=True)
class Limits:
    """What the user allows the pilot to do."""

    original_variables: tuple[Variable, ...]
    """The design space as the user defined it."""

    evaluation_budget: int
    allowed_actions: frozenset[ActionKind] = frozenset(ACTION_KINDS)
    max_restarts: int = 3
    """Restarts from another design allowed in a run."""

    @classmethod
    def of(
        cls,
        problem: ProblemSnapshot,
        allowed_actions: Sequence[ActionKind] | None = None,
        max_restarts: int = 3,
    ) -> "Limits":
        """The limits of a problem as the user set it up."""
        return cls(
            original_variables=problem.variables,
            evaluation_budget=problem.evaluation_budget,
            allowed_actions=frozenset(
                ACTION_KINDS if allowed_actions is None else ("none", *allowed_actions)
            ),
            max_restarts=max_restarts,
        )


RESTART_BUDGET_SHARE = 0.2
"""A restart needs at least this share of the evaluation budget left: a new
design needs iterations to settle."""


@dataclass(frozen=True)
class Checked:
    """A decision that respects the limits, and what was adjusted in it."""

    decision: Decision
    notes: tuple[str, ...] = ()


class RejectedDecisionError(ValueError):
    """A decision that breaks a limit."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__(
            "The decision was not applied:\n"
            + "\n".join(f"- {reason}" for reason in self.reasons)
            + "\nCorrect it and call submit_decision again."
        )


def check(
    decision: Decision,
    problem: ProblemSnapshot,
    limits: Limits,
    evaluations_used: int,
    algorithms: Mapping[str, AlgorithmInfo] | None = None,
    design: DesignView | None = None,
    restarts: int = 0,
) -> Checked:
    """Accept a decision, adjust it to the limits, or reject it.

    Args:
        decision: The decision of Claude.
        problem: The problem as it is now.
        limits: The limits set by the user.
        evaluations_used: The evaluations already spent.
        algorithms: The algorithms of the driver's kind, by name; GEMSEO's
            by default.
        design: The view of the design, when the model describes it.
        restarts: The restarts already applied in the run.

    Raises:
        RejectedDecisionError: When the decision breaks a limit.
    """
    action = decision.action
    if action.kind not in limits.allowed_actions:
        raise RejectedDecisionError([f"the action {action.kind} is not allowed here"])
    if action.kind not in ACTIONS_OF_DRIVER[problem.driver_kind]:
        raise RejectedDecisionError(
            [
                f"the action {action.kind} does not apply to "
                f"{DRIVER_NAMES[problem.driver_kind]}"
            ]
        )
    if action.kind in ("none", "stop"):
        return Checked(decision)
    if isinstance(action, ChangeSubScenario):
        catalog = algorithms or gemseo_algorithms("optimization")
        return _change_sub_scenario(decision, action, problem, catalog)
    remaining = limits.evaluation_budget - evaluations_used
    if remaining <= 0:
        raise RejectedDecisionError(
            ["the evaluation budget is spent; only stop is left"]
        )
    if isinstance(action, Steer):
        return _steer(decision, action, problem, evaluations_used, design)
    if isinstance(action, Restart):
        return _restart(
            decision, action, limits, remaining, evaluations_used, design, restarts
        )
    if algorithms is None:
        algorithms = gemseo_algorithms(problem.driver_kind)
    if isinstance(action, ChangeSettings):
        return _change_settings(decision, action, problem, remaining, algorithms)
    if isinstance(action, SwitchAlgorithm):
        return _switch_algorithm(decision, action, problem, remaining, algorithms)
    if isinstance(action, ChangeDesignSpace):
        return _change_design_space(decision, action, problem, limits)
    assert isinstance(action, AddSamples)
    return _add_samples(decision, action, problem, limits, remaining, algorithms)


def _change_settings(
    decision: Decision,
    action: ChangeSettings,
    problem: ProblemSnapshot,
    remaining: int,
    algorithms: Mapping[str, AlgorithmInfo],
) -> Checked:
    algorithm = algorithms.get(problem.algo_name)
    if algorithm is None:
        raise RejectedDecisionError(
            [f"the current algorithm {problem.algo_name} is unknown"]
        )
    settings, notes = _clip_iterations(action.settings, remaining)
    _check_settings(algorithm, {**problem.settings, **settings}, settings)
    return Checked(
        decision.model_copy(
            update={"action": action.model_copy(update={"settings": settings})}
        ),
        notes,
    )


def _switch_algorithm(
    decision: Decision,
    action: SwitchAlgorithm,
    problem: ProblemSnapshot,
    remaining: int,
    algorithms: Mapping[str, AlgorithmInfo],
) -> Checked:
    algorithm = _algorithm(action.algo_name, problem, algorithms)
    settings, notes = _clip_iterations(
        {"max_iter": remaining, **action.settings}, remaining
    )
    _check_settings(algorithm, settings, settings)
    return Checked(
        decision.model_copy(
            update={"action": action.model_copy(update={"settings": settings})}
        ),
        notes,
    )


def _change_design_space(
    decision: Decision,
    action: ChangeDesignSpace,
    problem: ProblemSnapshot,
    limits: Limits,
) -> Checked:
    reasons: list[str] = []
    notes: list[str] = []
    changes = [
        _variable_change(change, problem, limits, reasons, notes)
        for change in action.variables
    ]
    if reasons:
        raise RejectedDecisionError(reasons)
    return Checked(
        decision.model_copy(
            update={"action": action.model_copy(update={"variables": changes})}
        ),
        tuple(notes),
    )


def _restart(
    decision: Decision,
    action: Restart,
    limits: Limits,
    remaining: int,
    evaluations_used: int,
    design: DesignView | None,
    restarts: int,
) -> Checked:
    if design is None:
        raise RejectedDecisionError(
            [
                "the model does not describe the physics of its design: a "
                "restart from a transformed design is not available"
            ]
        )
    reasons = []
    if restarts >= limits.max_restarts:
        reasons.append(f"the {limits.max_restarts} restarts of this run are used")
    least = RESTART_BUDGET_SHARE * limits.evaluation_budget
    if remaining < least:
        reasons.append(
            f"{remaining} evaluations are left, fewer than the {least:g} a new "
            "design needs to settle"
        )
    base = action.base
    if isinstance(base, int) and not 0 <= base < evaluations_used:
        reasons.append(f"there is no evaluation {base} to start from")
    reasons += transform_errors(action.transforms, design.grid, evaluations_used)
    if reasons:
        raise RejectedDecisionError(reasons)
    return Checked(decision)


def _steer(
    decision: Decision,
    action: Steer,
    problem: ProblemSnapshot,
    evaluations_used: int,
    design: DesignView | None,
) -> Checked:
    reasons = []
    if action.anticipate is None and not action.transforms and not action.variables:
        reasons.append(
            "the steering moves nothing: anticipate, transforms or variables"
        )
    if action.transforms:
        if design is None:
            reasons.append(
                "the model does not describe the physics of its design: no "
                "transformation on a grid"
            )
        else:
            reasons += transform_errors(
                action.transforms, design.grid, evaluations_used
            )
    for change in action.variables:
        variable = problem.variable(change.name)
        if variable is None:
            reasons.append(f"there is no design variable named {change.name}")
            continue
        value = _array(change.value, variable.size, f"{change.name} value", reasons)
        if (
            value is not None
            and value.size
            and ((value < variable.lower).any() or (value > variable.upper).any())
        ):
            reasons.append(f"the value of {change.name} is outside its bounds")
    if reasons:
        raise RejectedDecisionError(reasons)
    return Checked(decision)


def _change_sub_scenario(
    decision: Decision,
    action: ChangeSubScenario,
    problem: ProblemSnapshot,
    algorithms: Mapping[str, AlgorithmInfo],
) -> Checked:
    sub = next(
        (item for item in problem.sub_scenarios if item.name == action.scenario), None
    )
    if sub is None:
        names = ", ".join(item.name for item in problem.sub_scenarios) or "none"
        raise RejectedDecisionError(
            [f"there is no sub-optimization named {action.scenario} ({names})"]
        )
    if action.algo_name is None and not action.settings:
        raise RejectedDecisionError(["the decision changes nothing"])
    name = action.algo_name or sub.algo_name
    algorithm = algorithms.get(name)
    if algorithm is None:
        raise RejectedDecisionError([f"no optimization algorithm named {name}"])
    # The same algorithm keeps its other settings; another one starts afresh.
    settings = {**sub.settings, **action.settings} if name == sub.algo_name else {}
    settings = settings or dict(action.settings)
    _check_settings(algorithm, settings, action.settings)
    return Checked(decision)


def _add_samples(
    decision: Decision,
    action: AddSamples,
    problem: ProblemSnapshot,
    limits: Limits,
    remaining: int,
    algorithms: Mapping[str, AlgorithmInfo],
) -> Checked:
    algorithm = _algorithm(action.algo_name, problem, algorithms)
    reasons: list[str] = []
    notes: list[str] = []
    for change in action.region:
        if change.value is not None:
            reasons.append(f"the region gives a value to {change.name}; it has none")
        # A region only bounds the samples: no starting value to adjust.
        _variable_change(change, problem, limits, reasons, [])
    if reasons:
        raise RejectedDecisionError(reasons)
    n_samples = min(action.n_samples, remaining)
    if n_samples < action.n_samples:
        notes.append(
            f"n_samples reduced from {action.n_samples} to {n_samples}, "
            "the evaluations left in the budget"
        )
    settings = dict(action.settings)
    if "n_samples" in algorithm.settings_model.model_fields:
        settings["n_samples"] = n_samples
    _check_settings(algorithm, settings, settings)
    return Checked(
        decision.model_copy(
            update={"action": action.model_copy(update={"n_samples": n_samples})}
        ),
        tuple(notes),
    )


def _algorithm(
    name: str, problem: ProblemSnapshot, algorithms: Mapping[str, AlgorithmInfo]
) -> AlgorithmInfo:
    algorithm = algorithms.get(name)
    if algorithm is None:
        raise RejectedDecisionError(
            [
                f"no algorithm named {name} is installed for "
                f"{DRIVER_NAMES[problem.driver_kind]}"
            ]
        )
    reasons = incompatibilities(algorithm, problem)
    if reasons:
        raise RejectedDecisionError([f"{name} {reason}" for reason in reasons])
    return algorithm


def _clip_iterations(
    settings: Mapping[str, Any], remaining: int
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """The settings with ``max_iter`` at most the evaluations left."""
    settings = dict(settings)
    max_iter = settings.get("max_iter")
    if isinstance(max_iter, int) and max_iter > remaining:
        settings["max_iter"] = remaining
        return settings, (
            f"max_iter reduced from {max_iter} to {remaining}, "
            "the evaluations left in the budget",
        )
    return settings, ()


def _check_settings(
    algorithm: AlgorithmInfo, settings: Mapping[str, Any], changed: Mapping[str, Any]
) -> None:
    managed = sorted(MANAGED_SETTINGS & changed.keys())
    reasons = [f"setting {name} is managed by the pilot" for name in managed]
    reasons += settings_errors(algorithm, settings)
    if reasons:
        raise RejectedDecisionError(reasons)


def _variable_change(
    change: VariableChange,
    problem: ProblemSnapshot,
    limits: Limits,
    reasons: list[str],
    notes: list[str],
) -> VariableChange:
    """Check the change of a variable; adjust its starting value if needed."""
    current = problem.variable(change.name)
    original = next(
        (item for item in limits.original_variables if item.name == change.name), None
    )
    if current is None or original is None:
        reasons.append(f"there is no design variable named {change.name}")
        return change
    size = current.size
    lower = _array(change.lower, size, f"{change.name} lower", reasons)
    upper = _array(change.upper, size, f"{change.name} upper", reasons)
    value = _array(change.value, size, f"{change.name} value", reasons)
    if lower is None or upper is None or value is None:
        return change
    lower = current.lower if not lower.size else lower
    upper = current.upper if not upper.size else upper
    if (lower < original.lower).any() or (upper > original.upper).any():
        reasons.append(
            f"the bounds of {change.name} go beyond the ones the user set "
            f"({_text(original.lower)} to {_text(original.upper)})"
        )
    if (lower > upper).any():
        reasons.append(f"a lower bound of {change.name} is above its upper bound")
    if current.integer and not all(_integral(item) for item in (lower, upper, value)):
        reasons.append(f"{change.name} is an integer variable")
    if value.size:
        if ((value < lower) | (value > upper)).any():
            reasons.append(f"the value of {change.name} is outside its bounds")
        return change
    if (
        current.value is not None
        and ((current.value < lower) | (current.value > upper)).any()
    ):
        notes.append(f"the starting value of {change.name} moved into its new bounds")
        clipped = np.clip(current.value, lower, upper)
        return change.model_copy(update={"value": [float(item) for item in clipped]})
    return change


def _array(
    values: Values | None, size: int, what: str, reasons: list[str]
) -> Array | None:
    """The values for each component; empty if not given, ``None`` if wrong."""
    if values is None:
        return np.empty(0)
    array = np.asarray(values, dtype=float).ravel()
    if array.size == 1:
        array = np.full(size, array[0])
    if array.size != size:
        reasons.append(f"{what} has {array.size} values instead of {size}")
        return None
    if not np.isfinite(array).all():
        reasons.append(f"{what} has values that are not finite")
        return None
    return array


def _integral(array: Array) -> bool:
    return bool(np.all(array == np.round(array)))


def _text(array: Array) -> str:
    return (
        f"{array[0]:g}"
        if np.all(array == array[0])
        else np.array2string(array, precision=4)
    )
