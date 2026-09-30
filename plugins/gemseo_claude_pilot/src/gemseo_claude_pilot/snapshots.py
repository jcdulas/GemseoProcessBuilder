"""Frozen pictures of a problem and of its history (spec § 6.1).

The detectors, the guardrails and the context sent to Claude work on these
snapshots, never on the GEMSEO objects: they are pure, fast to test, and the
advisor thread never reads a problem that the optimizer is changing.
"""

import inspect
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any
from typing import Literal

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    from gemseo.algos.optimization_problem import OptimizationProblem

Array = NDArray[np.float64]

DriverKind = Literal["optimization", "doe"]

DRIVER_NAMES: dict[DriverKind, str] = {
    "optimization": "an optimization",
    "doe": "a DOE",
}
"""The kinds of driver in a sentence."""
Gradients = Literal["exact", "approximated", "none"]

RECENT_POINTS = 10
"""Number of last design points a history keeps in full."""


@dataclass(frozen=True)
class Variable:
    """A design variable, with its bounds and current value."""

    name: str
    size: int
    lower: Array
    upper: Array
    value: Array | None = None
    integer: bool = False


@dataclass(frozen=True)
class Constraint:
    """A constraint, as the user named it and as GEMSEO stores it."""

    name: str
    standardized_name: str
    type: Literal["eq", "ineq"]
    size: int = 1


@dataclass(frozen=True)
class Component:
    """A component of the model; its source is only sent at the ``full`` level."""

    name: str
    description: str = ""
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    source: str = ""


@dataclass(frozen=True)
class SubScenario:
    """A sub-optimization of a BiLevel study, run at each system evaluation."""

    name: str
    algo_name: str
    settings: Mapping[str, Any] = field(default_factory=dict)
    design_variables: tuple[str, ...] = ()
    objective: str = ""


@dataclass(frozen=True)
class ProblemSnapshot:
    """What the pilot knows of the problem and of the way it is solved."""

    variables: tuple[Variable, ...]
    objective: str
    algo_name: str
    evaluation_budget: int
    driver_kind: DriverKind = "optimization"
    standardized_objective: str = ""
    minimize: bool = True
    constraints: tuple[Constraint, ...] = ()
    observables: tuple[str, ...] = ()
    settings: Mapping[str, Any] = field(default_factory=dict)
    gradients: Gradients = "exact"
    equality_tolerance: float = 1e-2
    inequality_tolerance: float = 1e-4
    formulation: str = ""
    components: tuple[Component, ...] = ()
    sub_scenarios: tuple[SubScenario, ...] = ()
    algorithm_state: tuple[Mapping[str, Any], ...] = ()
    """The reports of the outer iterations of an algorithm that gives them
    (``LSO_MMA``, ``LSO_GCMMA``), oldest first."""

    @property
    def design_size(self) -> int:
        """The number of components of the design vector."""
        return sum(variable.size for variable in self.variables)

    @property
    def lower_bounds(self) -> Array:
        """The lower bounds of the design vector."""
        return np.concatenate([variable.lower for variable in self.variables])

    @property
    def upper_bounds(self) -> Array:
        """The upper bounds of the design vector."""
        return np.concatenate([variable.upper for variable in self.variables])

    def variable(self, name: str) -> Variable | None:
        """The design variable of this name, if there is one."""
        return next((item for item in self.variables if item.name == name), None)


@dataclass(frozen=True)
class HistorySnapshot:
    """The evaluations of a problem so far, one entry per evaluation.

    Constraint values are standardized as GEMSEO solves them: an inequality is
    satisfied when it is at most 0, an equality when it is 0, both within their
    tolerance. Design points are normalized by their bounds.
    """

    objective: Array
    """The objective, with the sign the user sees; NaN when missing."""

    violation: Array
    """The largest constraint violation beyond tolerance (0 when feasible, NaN
    while a constraint is missing)."""

    step: Array
    """The normalized distance from the previous point (RMS over components)."""

    recent_x: Array
    """The last normalized design points, one per row."""

    first_x: Array
    """The first design point, not normalized."""

    best_x: Array
    """The best design point, not normalized."""

    minimize: bool = True
    constraints: Mapping[str, Array] = field(default_factory=dict)
    """The largest standardized value of each constraint, by user name."""

    gradient_norm: Array | None = None
    """The norm of the objective gradient; NaN where it was not computed."""

    best_gradient: Array | None = None
    """The gradient of the standardized objective at the best point, if known."""

    best_constraints: Mapping[str, Array] = field(default_factory=dict)
    """The standardized values of each constraint of several components at the
    best point, by user name: large vectors are summarized from them."""

    @property
    def n_evaluations(self) -> int:
        """The number of evaluations."""
        return len(self.objective)

    @property
    def failed(self) -> NDArray[np.bool_]:
        """The evaluations whose objective is missing or not finite."""
        return np.asarray(~np.isfinite(self.objective))

    @property
    def standardized_objective(self) -> Array:
        """The objective to minimize."""
        return self.objective if self.minimize else -self.objective

    @property
    def feasible(self) -> NDArray[np.bool_]:
        """The evaluations that satisfy every constraint and did not fail."""
        return np.asarray((self.violation <= 0) & ~self.failed)

    @property
    def best_index(self) -> int:
        """The best evaluation, as in the results (SPEC § 12.2); -1 if none.

        The feasible one with the smallest objective, else the least violated.
        """
        return best_index(self.standardized_objective, self.violation)


def best_index(objective: Array, violation: Array) -> int:
    """The feasible point with the smallest objective, else the least violated."""
    valid = np.isfinite(objective)
    feasible = valid & (violation <= 0)
    if feasible.any():
        return int(np.flatnonzero(feasible)[np.argmin(objective[feasible])])
    measured = valid & np.isfinite(violation)
    if measured.any():
        return int(np.flatnonzero(measured)[np.argmin(violation[measured])])
    return int(np.flatnonzero(valid)[0]) if valid.any() else -1


def normalization(lower: Array, upper: Array) -> tuple[Array, Array]:
    """The offset and scale mapping the bounds to [0, 1].

    Components with an infinite or empty range are not normalized.
    """
    finite = np.isfinite(lower) & np.isfinite(upper) & (upper > lower)
    offset = np.where(finite, lower, 0.0)
    scale = np.where(finite, upper - lower, 1.0)
    return offset, scale


def snapshot_problem(
    problem: "OptimizationProblem",
    algo_name: str,
    evaluation_budget: int,
    settings: Mapping[str, Any] | None = None,
    driver_kind: DriverKind = "optimization",
    formulation: str = "",
    components: tuple[Component, ...] = (),
    sub_scenarios: tuple[SubScenario, ...] = (),
    gradients: Gradients | None = None,
) -> ProblemSnapshot:
    """A snapshot of a GEMSEO optimization problem.

    Args:
        problem: The problem.
        algo_name: The algorithm solving it.
        evaluation_budget: The number of evaluations the user allows.
        settings: The settings of the algorithm.
        driver_kind: Whether the problem is optimized or sampled.
        formulation: The name of the MDO formulation.
        components: The components of the model.
        sub_scenarios: The sub-optimizations of a BiLevel study.
        gradients: Whether the problem has gradients, when its
            differentiation method does not tell (a BiLevel system has none).
    """
    space = problem.design_space
    integer = space.DesignVariableType.INTEGER
    current = space.get_current_value(as_dict=True)
    variables = tuple(
        Variable(
            name=name,
            size=int(space.get_size(name)),
            lower=np.asarray(space.get_lower_bound(name), dtype=float),
            upper=np.asarray(space.get_upper_bound(name), dtype=float),
            value=None if name not in current else np.asarray(current[name], float),
            integer=space.get_type(name) == integer,
        )
        for name in space.variable_names
    )
    constraints = tuple(
        Constraint(
            name=function.original_name or function.name,
            standardized_name=function.name,
            type="eq" if function.f_type == "eq" else "ineq",
            size=int(function.dim or 1),
        )
        for function in problem.constraints
    )
    method = str(problem.differentiation_method)
    derived: Gradients = "approximated"
    if gradients is not None:
        derived = gradients
    elif method == "user":
        derived = "exact"
    elif method == "no_derivative":
        derived = "none"
    return ProblemSnapshot(
        variables=variables,
        objective=problem.objective_name,
        standardized_objective=problem.objective.name,
        minimize=problem.minimize_objective,
        constraints=constraints,
        observables=tuple(observable.name for observable in problem.observables),
        algo_name=algo_name,
        settings=dict(settings or {}),
        evaluation_budget=evaluation_budget,
        driver_kind=driver_kind,
        gradients=derived,
        equality_tolerance=problem.tolerances.equality,
        inequality_tolerance=problem.tolerances.inequality,
        formulation=formulation,
        components=components,
        sub_scenarios=sub_scenarios,
    )


def components_of(scenario: Any, with_source: bool = False) -> tuple[Component, ...]:
    """The components of a scenario, with their source code if asked.

    The sub-scenarios of a BiLevel study are not components: their own
    disciplines are.
    """
    components = []
    for discipline in disciplines_of(scenario):
        kind = type(discipline)
        source = ""
        if with_source:
            try:
                source = inspect.getsource(kind)
            except (OSError, TypeError):
                source = ""
        description = (inspect.getdoc(kind) or "").split("\n\n")[0]
        if kind.__name__ == "SurrogateDiscipline":
            description = surrogate_description(discipline)
        components.append(
            Component(
                name=discipline.name,
                description=description,
                inputs=tuple(discipline.io.input_grammar.names),
                outputs=tuple(discipline.io.output_grammar.names),
                source=source,
            )
        )
    return tuple(components)


def disciplines_of(scenario: Any) -> list[Any]:
    """The disciplines of a scenario and of its sub-scenarios."""
    disciplines = []
    for discipline in scenario.formulation.disciplines:
        if hasattr(discipline, "formulation"):
            disciplines.extend(disciplines_of(discipline))
        else:
            disciplines.append(discipline)
    return disciplines


def surrogate_description(discipline: Any) -> str:
    """What a surrogate is, and how far it can be trusted."""
    model = discipline.regression_model
    text = f"Surrogate model ({type(model).__name__})"
    try:
        from gemseo.mlearning.regression.quality.r2_measure import R2Measure

        size = len(model.learning_set)
        r2 = np.atleast_1d(R2Measure(model).compute_learning_measure())
    except Exception:  # The quality is a hint: a model without it stays described.
        return text
    scores = ", ".join(f"{value:.3f}" for value in r2)
    return f"{text} trained on {size} samples; R2 on its training data: {scores}"


def sub_scenarios_of(scenario: Any) -> tuple[SubScenario, ...]:
    """The sub-optimizations of a BiLevel study; none for another formulation."""
    formulation = scenario.formulation
    if not hasattr(formulation, "get_sub_scenarios"):
        return ()
    subs = []
    for sub in formulation.get_sub_scenarios():
        settings = getattr(sub, "_settings", None)
        algo_name = getattr(settings, "algo_name", "") if settings else ""
        values = dict(getattr(settings, "algo_settings", {}) or {}) if settings else {}
        problem = sub.formulation.optimization_problem
        subs.append(
            SubScenario(
                name=sub.name,
                algo_name=str(getattr(algo_name, "value", algo_name)),
                settings=values,
                design_variables=tuple(problem.design_space.variable_names),
                objective=problem.objective_name,
            )
        )
    return tuple(subs)


Entry = tuple[Array, Mapping[str, Any]]
"""A design point and the values computed there."""

GRADIENT_TAG = "@"
"""The prefix of the gradients in a GEMSEO database."""


def database_entries(problem: "OptimizationProblem") -> list[Entry]:
    """A copy of the entries of the database of a problem.

    Cheap: the arrays are shared, only the lists and mappings are copied. The
    advisor thread reads the copy while the optimizer adds to the database.
    """
    return [(x.unwrap(), dict(values)) for x, values in problem.database.items()]


def snapshot_history(
    problem: "OptimizationProblem", snapshot: ProblemSnapshot
) -> HistorySnapshot:
    """A snapshot of the evaluations stored in the database of a problem."""
    return history_from_entries(database_entries(problem), snapshot)


def history_from_entries(
    entries: Sequence[Entry], snapshot: ProblemSnapshot
) -> HistorySnapshot:
    """A snapshot of evaluations.

    A point whose constraints are not all computed yet is not feasible.
    """
    objective_name = snapshot.standardized_objective or snapshot.objective
    gradient_name = GRADIENT_TAG + objective_name
    sign = 1.0 if snapshot.minimize else -1.0
    names = _constraint_keys(snapshot.constraints)
    offset, scale = normalization(snapshot.lower_bounds, snapshot.upper_bounds)

    objective: list[float] = []
    violation: list[float] = []
    step: list[float] = []
    gradient_norm: list[float] = []
    constraints: dict[str, list[float]] = {name: [] for name in names.values()}
    recent: list[Array] = []
    first_x = best_x = np.full(snapshot.design_size, np.nan)
    previous: Array | None = None
    best_gradient: Array | None = None
    for raw_x, values in entries:
        x = np.asarray(raw_x, dtype=float)
        normalized = (x - offset) / scale
        objective.append(sign * _scalar(values.get(objective_name)))
        worst = 0.0
        for constraint in snapshot.constraints:
            value = _constraint_value(
                values.get(constraint.standardized_name), constraint
            )
            constraints[names[constraint.standardized_name]].append(value)
            tolerance = (
                snapshot.equality_tolerance
                if constraint.type == "eq"
                else snapshot.inequality_tolerance
            )
            worst = max(worst, value - tolerance) if np.isfinite(value) else np.nan
        violation.append(worst)
        step.append(0.0 if previous is None else _rms(normalized - previous))
        gradient = values.get(gradient_name)
        gradient_norm.append(
            np.nan if gradient is None else float(np.linalg.norm(gradient))
        )
        if previous is None:
            first_x = x
        previous = normalized
        recent = [*recent[-(RECENT_POINTS - 1) :], normalized]

    objective_array = np.asarray(objective)
    violation_array = np.asarray(violation)
    best = best_index(sign * objective_array, violation_array)
    best_constraints: dict[str, Array] = {}
    if best >= 0:
        best_x = np.asarray(entries[best][0], dtype=float)
        gradient = entries[best][1].get(gradient_name)
        if gradient is not None:
            best_gradient = np.asarray(gradient, dtype=float).ravel()
        for constraint in snapshot.constraints:
            vector = entries[best][1].get(constraint.standardized_name)
            if constraint.size > 1 and vector is not None:
                best_constraints[names[constraint.standardized_name]] = np.asarray(
                    vector, dtype=float
                ).ravel()
    return HistorySnapshot(
        objective=objective_array,
        violation=violation_array,
        step=np.asarray(step),
        recent_x=np.asarray(recent).reshape(len(recent), snapshot.design_size),
        first_x=first_x,
        best_x=best_x,
        minimize=snapshot.minimize,
        constraints={name: np.asarray(values) for name, values in constraints.items()},
        gradient_norm=np.asarray(gradient_norm),
        best_gradient=best_gradient,
        best_constraints=best_constraints,
    )


def _constraint_keys(constraints: tuple[Constraint, ...]) -> dict[str, str]:
    """The user name of each constraint, or its GEMSEO name if two share one."""
    counts: dict[str, int] = {}
    for constraint in constraints:
        counts[constraint.name] = counts.get(constraint.name, 0) + 1
    return {
        constraint.standardized_name: (
            constraint.name
            if counts[constraint.name] == 1
            else constraint.standardized_name
        )
        for constraint in constraints
    }


def _scalar(value: Any) -> float:
    if value is None:
        return np.nan
    return float(np.asarray(value, dtype=float).ravel()[0])


def _constraint_value(value: Any, constraint: Constraint) -> float:
    if value is None:
        return np.nan
    array = np.asarray(value, dtype=float).ravel()
    return float(np.abs(array).max() if constraint.type == "eq" else array.max())


def _rms(vector: Array) -> float:
    return float(np.sqrt(np.mean(vector**2))) if vector.size else 0.0
