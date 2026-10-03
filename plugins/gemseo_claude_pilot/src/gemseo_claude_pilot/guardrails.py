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
from gemseo_claude_pilot.algorithms import default_settings
from gemseo_claude_pilot.algorithms import gemseo_algorithms
from gemseo_claude_pilot.algorithms import incompatibilities
from gemseo_claude_pilot.algorithms import same_setting
from gemseo_claude_pilot.algorithms import settings_errors
from gemseo_claude_pilot.decisions import ACTION_KINDS
from gemseo_claude_pilot.decisions import ActionKind
from gemseo_claude_pilot.decisions import AddSamples
from gemseo_claude_pilot.decisions import Adopt
from gemseo_claude_pilot.decisions import ChangeDesignSpace
from gemseo_claude_pilot.decisions import ChangeSettings
from gemseo_claude_pilot.decisions import ChangeSubScenario
from gemseo_claude_pilot.decisions import Compare
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.decisions import Explore
from gemseo_claude_pilot.decisions import Relax
from gemseo_claude_pilot.decisions import Restart
from gemseo_claude_pilot.decisions import RestoreFeasibility
from gemseo_claude_pilot.decisions import Resume
from gemseo_claude_pilot.decisions import Steer
from gemseo_claude_pilot.decisions import StopExplorations
from gemseo_claude_pilot.decisions import SwitchAlgorithm
from gemseo_claude_pilot.decisions import Tighten
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
            "compare",
            "restore_feasibility",
            "explore",
            "adopt",
            "stop_explorations",
            "relax",
            "tighten",
            "resume",
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

    max_comparisons: int = 2
    """Comparisons of strategies allowed in a run."""

    require_assessment: bool = False
    """Whether an action must come with the critique of its analysis."""

    exploration: bool = False
    """Whether the user gave the means to explore (a scenario factory)."""

    max_exploration_processes: int = 3
    max_exploration_iterations: int = 50
    max_explorations: int = 2

    max_relaxations: int = 2
    """Relaxations of constraints allowed in a run."""

    max_relaxed_share: float = 0.2
    """The share of the components of the constraints relaxed at once, at most."""

    max_relaxation: float = 1.0
    """The largest amount of a relaxation, in the units of the constraints."""

    max_resumes: int = 3
    """Returns to an earlier checkpoint allowed in a run."""

    @classmethod
    def of(
        cls,
        problem: ProblemSnapshot,
        allowed_actions: Sequence[ActionKind] | None = None,
        max_restarts: int = 3,
        max_comparisons: int = 2,
    ) -> "Limits":
        """The limits of a problem as the user set it up."""
        return cls(
            original_variables=problem.variables,
            evaluation_budget=problem.evaluation_budget,
            allowed_actions=frozenset(
                ACTION_KINDS if allowed_actions is None else ("none", *allowed_actions)
            ),
            max_restarts=max_restarts,
            max_comparisons=max_comparisons,
        )


RESTART_BUDGET_SHARE = 0.2
"""A restart needs at least this share of the evaluation budget left: a new
design needs iterations to settle."""

COMPARISON_BUDGET_SHARE = 0.5
"""The branches of a comparison may spend at most this share of the evaluations
left: the branch kept goes on, the others are the price of the answer."""

LSO_ALGORITHMS = ("LSO_MMA", "LSO_GCMMA")
"""The algorithms of the large-scale optimizer, which report their outer
iterations and save their state."""

NO_PREDICTION = frozenset({"stop"})
"""The actions whose assessment needs no prediction: nothing follows a stop."""

RESERVED_SETTINGS = frozenset({"max_iter", "resume_from", "save_state", "method"})
"""Settings a comparison sets itself."""


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
    comparisons: int = 0,
    explorations: Mapping[str, Any] | None = None,
    relaxation: Mapping[str, Any] | None = None,
    checkpoints: Mapping[str, Any] | None = None,
    current_settings: Mapping[str, Any] | None = None,
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
        comparisons: The comparisons of strategies already made in the run.
        explorations: Where the explorations of the run stand: ``made``, whether
            one is ``running`` and the ``finished`` labels, which may be adopted.
        relaxation: Where the relaxation of constraints stands: ``made``, whether
            one is ``active`` and the ``constraints`` (name and size) that
            have multipliers.
        checkpoints: The ``available`` ids of the checkpoints and the ``resumes``
            already made.
        current_settings: The values the settings of the running algorithm have
            now, defaults and live changes included, when the algorithm tells
            them; else the defaults overlaid with the settings of the problem.

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
    if limits.require_assessment and action.kind != "none":
        reasons = assessment_reasons(decision)
        if reasons:
            raise RejectedDecisionError(reasons)
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
    if isinstance(action, RestoreFeasibility):
        return _restore_feasibility(decision, problem)
    if isinstance(action, Explore):
        return _explore(decision, action, problem, limits, design, explorations or {})
    if isinstance(action, Adopt):
        return _adopt(decision, action, problem, explorations or {})
    if isinstance(action, StopExplorations):
        return _stop_explorations(decision, action, explorations or {})
    if isinstance(action, Relax):
        return _relax(decision, action, problem, limits, relaxation or {})
    if isinstance(action, Tighten):
        return _tighten(decision, problem, relaxation or {})
    if isinstance(action, Resume):
        return _resume(decision, action, problem, limits, checkpoints or {})
    if isinstance(action, Compare):
        if algorithms is None:
            algorithms = gemseo_algorithms(problem.driver_kind)
        return _compare(
            decision, action, problem, limits, remaining, comparisons, algorithms
        )
    if algorithms is None:
        algorithms = gemseo_algorithms(problem.driver_kind)
    if isinstance(action, ChangeSettings):
        return _change_settings(
            decision, action, problem, remaining, algorithms, current_settings
        )
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
    current_settings: Mapping[str, Any] | None = None,
) -> Checked:
    algorithm = algorithms.get(problem.algo_name)
    if algorithm is None:
        raise RejectedDecisionError(
            [f"the current algorithm {problem.algo_name} is unknown"]
        )
    settings, notes = _clip_iterations(action.settings, remaining)
    _check_settings(algorithm, {**problem.settings, **settings}, settings)
    current = {
        **default_settings(algorithm),
        **problem.settings,
        **(current_settings or {}),
    }
    unchanged = {
        name: value
        for name, value in settings.items()
        if name in current and same_setting(current[name], value)
    }
    if unchanged and len(unchanged) == len(settings):
        raise RejectedDecisionError(
            [
                f"{name} is already {current[name]!r}: this changes nothing "
                "(the values the settings have now are in the context)"
                for name in unchanged
            ]
        )
    notes = (
        *notes,
        *(f"{name} already was {current[name]!r}" for name in unchanged),
    )
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


def assessment_reasons(decision: Decision) -> list[str]:
    """What is missing from the critique that must come with an action."""
    assessment = decision.assessment
    if assessment is None:
        return [
            "an action comes with its assessment: the hypotheses with the evidence "
            "for and against, where your analysis may be wrong, the alternatives "
            "you considered and a measurable prediction"
        ]
    if decision.action.kind not in NO_PREDICTION and assessment.prediction is None:
        return ["the assessment needs a prediction the next iterations can check"]
    return []


def _large_scale_reasons(problem: ProblemSnapshot) -> list[str]:
    """Why a decision for the large-scale optimizer does not apply, if it does not."""
    if problem.algo_name not in LSO_ALGORITHMS:
        return [
            f"this action applies to {' and '.join(LSO_ALGORITHMS)}, "
            f"not to {problem.algo_name}"
        ]
    if not problem.algorithm_state:
        return ["the optimizer has not reported an outer iteration yet"]
    return []


def _restore_feasibility(decision: Decision, problem: ProblemSnapshot) -> Checked:
    reasons = _large_scale_reasons(problem)
    if not reasons:
        last = problem.algorithm_state[-1]
        if float(last["max_constraint"]) <= problem.inequality_tolerance:
            reasons.append("the last iterate is feasible: there is nothing to restore")
    if reasons:
        raise RejectedDecisionError(reasons)
    return Checked(decision)


def _explore(
    decision: Decision,
    action: Explore,
    problem: ProblemSnapshot,
    limits: Limits,
    design: DesignView | None,
    explorations: Mapping[str, Any],
) -> Checked:
    reasons = _large_scale_reasons(problem)
    if not limits.exploration:
        reasons.append(
            "no exploration is possible: the pilot has no scenario factory to "
            "build the problem in other processes"
        )
    if int(explorations.get("made", 0)) >= limits.max_explorations:
        reasons.append(
            f"the {limits.max_explorations} explorations of this run are used"
        )
    if explorations.get("running"):
        reasons.append("an exploration is still running: wait for its results")
    # The memory available now sets how many can run at the same time.
    at_most = int(explorations.get("max_starts", limits.max_exploration_processes))
    if len(action.starts) > at_most:
        reasons.append(
            f"at most {at_most} explorations at a time: each takes memory "
            f"({explorations.get('free_memory_gb', '?')} GB are available)"
        )
    labels = [start.label for start in action.starts]
    if len(set(labels)) != len(labels):
        reasons.append("the labels of the starts must differ")
    for start in action.starts:
        if (
            start.anticipate is None
            and not start.transforms
            and not start.variables
            and start.perturb is None
            and start.base == "current"
        ):
            reasons.append(f"start {start.label} is the current iterate itself")
        if start.anticipate is not None and start.base != "current":
            reasons.append(f"start {start.label}: anticipate needs the current iterate")
        if start.transforms:
            if design is None:
                reasons.append(
                    f"start {start.label}: the model does not describe the physics "
                    "of its design: no transformation on a grid"
                )
            else:
                reasons += [
                    f"start {start.label}: {reason}"
                    for reason in transform_errors(start.transforms, design.grid, 10**9)
                ]
        reasons += [
            f"start {start.label}: {reason}"
            for reason in _variables_reasons(start.variables, problem)
        ]
    if reasons:
        raise RejectedDecisionError(reasons)
    cap = limits.max_exploration_iterations
    if action.iterations <= cap:
        return Checked(decision)
    clipped = action.model_copy(update={"iterations": cap})
    return Checked(
        decision.model_copy(update={"action": clipped}),
        (
            f"the explorations run {cap} outer iterations at most, "
            f"not {action.iterations}",
        ),
    )


def _relax(
    decision: Decision,
    action: Relax,
    problem: ProblemSnapshot,
    limits: Limits,
    relaxation: Mapping[str, Any],
) -> Checked:
    reasons = _large_scale_reasons(problem)
    if int(relaxation.get("made", 0)) >= limits.max_relaxations:
        reasons.append(f"the {limits.max_relaxations} relaxations of this run are used")
    if relaxation.get("active"):
        reasons.append(
            "a relaxation is under way: let it bring its constraints back "
            "(or tighten them) before relaxing others"
        )
    sizes: Mapping[str, int] = relaxation.get("constraints") or {}
    if not sizes:
        reasons.append("the optimizer has no multiplier to choose the constraints by")
    if action.amount > limits.max_relaxation:
        reasons.append(
            f"a relaxation of at most {limits.max_relaxation:g} "
            f"(in the units of the constraints), not {action.amount:g}"
        )
    chosen = 0
    for batch in action.batches:
        name = batch.constraint
        if name is None and len(sizes) == 1:
            name = next(iter(sizes))
        if name is None or name not in sizes:
            reasons.append(
                f"unknown constraint {batch.constraint}; the constraints are: "
                f"{', '.join(sizes) or 'none'}"
            )
            continue
        if batch.indices is not None:
            if min(batch.indices) < 0 or max(batch.indices) >= sizes[name]:
                reasons.append(
                    f"the components of {name} are numbered 0 to {sizes[name] - 1}"
                )
            chosen += len(set(batch.indices))
        elif batch.top is not None:
            chosen += min(batch.top, sizes[name])
    cap = max(int(limits.max_relaxed_share * sum(sizes.values())), 1)
    if chosen > cap:
        reasons.append(
            f"at most {cap} components ({limits.max_relaxed_share:.0%} of the "
            f"constraints) can be relaxed at once, not {chosen}"
        )
    if reasons:
        raise RejectedDecisionError(reasons)
    return Checked(decision)


def _tighten(
    decision: Decision, problem: ProblemSnapshot, relaxation: Mapping[str, Any]
) -> Checked:
    reasons = _large_scale_reasons(problem)
    if not relaxation.get("active"):
        reasons.append("no constraint is relaxed")
    if reasons:
        raise RejectedDecisionError(reasons)
    return Checked(decision)


def _resume(
    decision: Decision,
    action: Resume,
    problem: ProblemSnapshot,
    limits: Limits,
    checkpoints: Mapping[str, Any],
) -> Checked:
    reasons = _large_scale_reasons(problem)
    available = [item["id"] for item in checkpoints.get("saved", [])]
    if action.checkpoint not in available:
        known = ", ".join(available) or "none is saved yet"
        reasons.append(f"no checkpoint named {action.checkpoint} ({known})")
    if int(checkpoints.get("resumes", 0)) >= limits.max_resumes:
        reasons.append(f"the {limits.max_resumes} returns to a checkpoint are used")
    reasons += _resume_settings_reasons(action.settings)
    if reasons:
        raise RejectedDecisionError(reasons)
    return Checked(decision)


def _resume_settings_reasons(settings: Mapping[str, Any]) -> list[str]:
    """Why settings given to a resumed run are not valid, if they are not."""
    if not settings:
        return []
    from gemseo_lso.core.settings import Settings
    from gemseo_lso.gemseo.live import LIVE_SETTINGS

    fixed = sorted(set(settings) - LIVE_SETTINGS)
    if fixed:
        return [f"{', '.join(fixed)} cannot change on a resume"]
    try:
        Settings(**settings)
    except (TypeError, ValueError) as error:
        return [str(error)]
    return []


def _stop_explorations(
    decision: Decision, action: StopExplorations, explorations: Mapping[str, Any]
) -> Checked:
    running = list(explorations.get("running", []))
    reasons = []
    if not running:
        reasons.append("no exploration is running")
    unknown = [label for label in action.explorations if label not in running]
    if running and unknown:
        reasons.append(
            f"no running exploration named {', '.join(unknown)} "
            f"(running: {', '.join(running)})"
        )
    if reasons:
        raise RejectedDecisionError(reasons)
    return Checked(decision)


def _adopt(
    decision: Decision,
    action: Adopt,
    problem: ProblemSnapshot,
    explorations: Mapping[str, Any],
) -> Checked:
    reasons = _large_scale_reasons(problem)
    finished = list(explorations.get("finished", []))
    if action.exploration not in finished:
        known = ", ".join(finished) or "none has ended"
        reasons.append(
            f"there is no ended exploration named {action.exploration} ({known})"
        )
    if reasons:
        raise RejectedDecisionError(reasons)
    return Checked(decision)


def _variables_reasons(changes: Sequence[Any], problem: ProblemSnapshot) -> list[str]:
    """Why values given to design variables are not valid, if they are not."""
    reasons: list[str] = []
    for change in changes:
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
    return reasons


def _compare(
    decision: Decision,
    action: Compare,
    problem: ProblemSnapshot,
    limits: Limits,
    remaining: int,
    comparisons: int,
    algorithms: Mapping[str, AlgorithmInfo],
) -> Checked:
    reasons = _large_scale_reasons(problem)
    if comparisons >= limits.max_comparisons:
        reasons.append(f"the {limits.max_comparisons} comparisons of this run are used")
    if reasons:
        raise RejectedDecisionError(reasons)
    for option in action.options:
        reserved = sorted(RESERVED_SETTINGS & option.settings.keys())
        reasons += [
            f"option {option.label}: setting {name} is set by the comparison"
            for name in reserved
        ]
        algorithm = algorithms.get(option.algo_name or problem.algo_name)
        if algorithm is None:
            reasons.append(f"option {option.label}: its algorithm is not installed")
            continue
        try:
            _check_settings(
                algorithm,
                {**problem.settings, **option.settings},
                option.settings,
            )
        except RejectedDecisionError as error:
            reasons += [f"option {option.label}: {reason}" for reason in error.reasons]
    last = problem.algorithm_state[-1]
    per_iteration = max(float(last["evaluation"]) / max(int(last["iteration"]), 1), 1.0)
    cost = action.iterations * (len(action.options) + 1) * per_iteration
    if cost > COMPARISON_BUDGET_SHARE * remaining:
        reasons.append(
            f"the branches would spend about {cost:.0f} evaluations, more than "
            f"{COMPARISON_BUDGET_SHARE:.0%} of the {remaining} left: fewer "
            "options or iterations"
        )
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
