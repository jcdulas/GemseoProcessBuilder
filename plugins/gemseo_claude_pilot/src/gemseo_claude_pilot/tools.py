"""The tools Claude may call (spec § 6.3).

``submit_decision`` ends an exchange with a decision. The other tools read
more of the problem and its history than the context gives; :class:`ToolAnswers`
answers them.
"""

import json
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any

import numpy as np

from gemseo_claude_pilot.algorithms import AlgorithmInfo
from gemseo_claude_pilot.algorithms import gemseo_algorithms
from gemseo_claude_pilot.algorithms import incompatibilities
from gemseo_claude_pilot.backends.base import ToolCall
from gemseo_claude_pilot.backends.base import ToolSpec
from gemseo_claude_pilot.context import component_states
from gemseo_claude_pilot.context import constraint_states
from gemseo_claude_pilot.decisions import decision_schema
from gemseo_claude_pilot.design import DesignView
from gemseo_claude_pilot.design import indicators
from gemseo_claude_pilot.design import transforms_help
from gemseo_claude_pilot.guardrails import MANAGED_SETTINGS
from gemseo_claude_pilot.privacy import Anonymizer
from gemseo_claude_pilot.privacy import DataLevel
from gemseo_claude_pilot.privacy import component_view
from gemseo_claude_pilot.snapshots import Array
from gemseo_claude_pilot.snapshots import Entry
from gemseo_claude_pilot.snapshots import HistorySnapshot
from gemseo_claude_pilot.snapshots import ProblemSnapshot

SUBMIT_DECISION = ToolSpec(
    name="submit_decision",
    description=(
        "Give your diagnosis of the run and at most one action. Call it once, "
        "at the end of your analysis."
    ),
    input_schema=decision_schema(),
)

_NAME = {"type": "string"}
_INDEX = {"type": "integer", "minimum": 0}

GET_ITERATIONS = ToolSpec(
    name="get_iterations",
    description=(
        "The evaluations in a range: objective, constraint values, and "
        "optionally some design variables."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "first": _INDEX,
            "last": _INDEX,
            "variables": {"type": "array", "items": _NAME},
        },
        "required": ["first", "last"],
    },
)

GET_VARIABLE = ToolSpec(
    name="get_variable",
    description=(
        "The bounds, history and gradient of a design variable, or of some of "
        "its components."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": _NAME,
            "components": {"type": "array", "items": _INDEX},
        },
        "required": ["name"],
    },
)

GET_CONSTRAINT = ToolSpec(
    name="get_constraint",
    description=(
        "The history of a constraint and its state at the best point; for a "
        "constraint of many components, the values of some of them at the best "
        "point (their states only when the data are anonymized)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": _NAME,
            "components": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Components to read at the best point, at most 20.",
            },
        },
        "required": ["name"],
    },
)

LIST_ALGORITHMS = ToolSpec(
    name="list_algorithms",
    description="The installed algorithms that can solve this problem.",
    input_schema={"type": "object", "properties": {}},
)

GET_ALGORITHM_SETTINGS = ToolSpec(
    name="get_algorithm_settings",
    description="The settings of an algorithm you may change, with their defaults.",
    input_schema={
        "type": "object",
        "properties": {"name": _NAME},
        "required": ["name"],
    },
)

GET_COMPONENT = ToolSpec(
    name="get_component",
    description=(
        "The inputs, outputs and description of a component, and its source "
        "code when the user allows it."
    ),
    input_schema={
        "type": "object",
        "properties": {"name": _NAME},
        "required": ["name"],
    },
)

_POINT = {
    "anyOf": [{"type": "string", "enum": ["best", "current", "start"]}, _INDEX],
    "description": "best, current, or an evaluation index (then only the design "
    "variable and the constraints).",
}

GET_DESIGN_VIEW = ToolSpec(
    name="get_design_view",
    description=(
        "A map of a field of the design on its grid, with its legend: the "
        "physical density, the stress ratio, the strain energy, the sign of the "
        "principal stress, the design variable, a constraint, the price of a "
        "constraint or the stationarity (the fields of the context's design)."
    ),
    input_schema={
        "type": "object",
        "properties": {"field": _NAME, "point": _POINT},
        "required": ["field"],
    },
)

GET_DESIGN_INDICATORS = ToolSpec(
    name="get_design_indicators",
    description=(
        "The physical indicators of the design at a point: material use, load "
        "path, members, checkerboards, dead material, stress hot spots."
    ),
    input_schema={
        "type": "object",
        "properties": {"point": _POINT},
    },
)

LIST_DESIGN_TRANSFORMS = ToolSpec(
    name="list_design_transforms",
    description="The transformations a restart may apply to a design, and the map.",
    input_schema={"type": "object", "properties": {}},
)

DESIGN_TOOLS = (GET_DESIGN_VIEW, GET_DESIGN_INDICATORS, LIST_DESIGN_TRANSFORMS)
"""The tools on the design, offered when the model describes its physics."""

READ_TOOLS = (
    GET_ITERATIONS,
    GET_VARIABLE,
    GET_CONSTRAINT,
    LIST_ALGORITHMS,
    GET_ALGORITHM_SETTINGS,
    GET_COMPONENT,
)

TOOLS = (*READ_TOOLS, SUBMIT_DECISION)

MAX_ROWS = 50
"""Evaluations a read tool returns at most."""

MAX_COMPONENTS = 20
"""Components of a variable a read tool returns at most."""


class ToolAnswers:
    """Answers the read tools from the snapshots of one call.

    Names and values are the ones Claude sees: anonymous and normalized in
    ``anonymized``.

    Args:
        problem: The problem, as it was when the call was prepared.
        history: Its evaluations.
        entries: The database entries the history was built from.
        level: What may be sent.
        anonymizer: The anonymizer of the run, in ``anonymized``.
        algorithms: The algorithms of the driver's kind; GEMSEO's by default.
        design: The design, when the model describes its physics.
    """

    def __init__(
        self,
        problem: ProblemSnapshot,
        history: HistorySnapshot,
        entries: Sequence[Entry],
        level: DataLevel = "no_code",
        anonymizer: Anonymizer | None = None,
        algorithms: Mapping[str, AlgorithmInfo] | None = None,
        design: DesignView | None = None,
    ) -> None:
        self._design = design
        self._problem = problem
        self._entries = entries
        self._level = level
        self._anonymizer = anonymizer if level == "anonymized" else None
        self._states = constraint_states(problem, history)
        self._vectors = dict(history.best_constraints)
        self._history = history
        if self._anonymizer is not None:
            self._history = self._anonymizer.history(history, problem)
        self._algorithms = algorithms
        self._offsets: dict[str, int] = {}
        start = 0
        for variable in problem.variables:
            self._offsets[variable.name] = start
            start += variable.size

    def __call__(self, call: ToolCall) -> str:
        """The answer to a tool call, as JSON.

        Raises:
            ValueError: When the tool or a name is unknown.
        """
        arguments = dict(call.input)
        answer: Any
        if call.name == GET_ITERATIONS.name:
            answer = self.iterations(
                int(arguments["first"]),
                int(arguments["last"]),
                list(arguments.get("variables") or []),
            )
        elif call.name == GET_VARIABLE.name:
            answer = self.variable(
                str(arguments["name"]), list(arguments.get("components") or [])
            )
        elif call.name == GET_CONSTRAINT.name:
            answer = self.constraint(
                str(arguments["name"]), list(arguments.get("components") or [])
            )
        elif call.name == LIST_ALGORITHMS.name:
            answer = self.list_algorithms()
        elif call.name == GET_ALGORITHM_SETTINGS.name:
            answer = self.algorithm_settings(str(arguments["name"]))
        elif call.name == GET_COMPONENT.name:
            answer = self.component(str(arguments["name"]))
        elif call.name == GET_DESIGN_VIEW.name:
            return self.design_view(
                str(arguments["field"]), arguments.get("point", "best")
            )
        elif call.name == GET_DESIGN_INDICATORS.name:
            answer = self.design_indicators(arguments.get("point", "best"))
        elif call.name == LIST_DESIGN_TRANSFORMS.name:
            answer = transforms_help(self._view().grid)
        else:
            raise ValueError(f"there is no tool named {call.name}")
        return json.dumps(answer, ensure_ascii=False)

    def iterations(
        self, first: int, last: int, variables: Sequence[str] = ()
    ) -> dict[str, Any]:
        """The evaluations from ``first`` to ``last``, at most ``MAX_ROWS``."""
        history = self._history
        indices = range(max(first, 0), min(last, history.n_evaluations - 1) + 1)
        names = [self._variable_name(name) for name in variables]
        rows = []
        for index in indices[:MAX_ROWS]:
            row: dict[str, Any] = {
                "evaluation": index,
                "objective": _number(history.objective[index]),
                "max_violation": _number(history.violation[index]),
                "constraints": {
                    name: _number(values[index])
                    for name, values in history.constraints.items()
                },
            }
            if names:
                row["variables"] = {
                    self._shown(name): _numbers(
                        self._values(name, index)[:MAX_COMPONENTS]
                    )
                    for name in names
                }
            rows.append(row)
        return {"evaluations": rows, "truncated": len(indices) > MAX_ROWS}

    def variable(self, name: str, components: Sequence[int] = ()) -> dict[str, Any]:
        """A design variable: bounds, values over the last evaluations, gradient."""
        real = self._variable_name(name)
        variable = self._problem.variable(real)
        assert variable is not None
        chosen = [i for i in components if 0 <= i < variable.size][:MAX_COMPONENTS]
        chosen = chosen or list(range(min(variable.size, MAX_COMPONENTS)))
        lower, upper = variable.lower, variable.upper
        if self._anonymizer is not None:
            lower = self._anonymizer.normalize(real, lower)
            upper = self._anonymizer.normalize(real, upper)
        n = self._history.n_evaluations
        answer: dict[str, Any] = {
            "name": name,
            "size": variable.size,
            "components": chosen,
            "lower": _numbers(lower[chosen]),
            "upper": _numbers(upper[chosen]),
            "history": [
                {
                    "evaluation": index,
                    "values": _numbers(self._values(real, index)[chosen]),
                }
                for index in range(max(n - MAX_ROWS, 0), n)
            ],
        }
        gradient = self._history.best_gradient
        if gradient is not None and gradient.size == self._problem.design_size:
            start = self._offsets[real]
            answer["objective_gradient_at_best"] = _numbers(
                gradient[start : start + variable.size][chosen]
            )
        return answer

    def constraint(self, name: str, components: Sequence[int] = ()) -> dict[str, Any]:
        """A constraint: its values over the last evaluations, its state at best.

        For a constraint of several components, the values of some of them at
        the best point (their states in ``anonymized``).
        """
        real = name
        if self._anonymizer is not None:
            real = self._anonymizer.real_name(name) or ""
        constraint = next(
            (item for item in self._problem.constraints if item.name == real), None
        )
        if constraint is None:
            raise ValueError(f"there is no constraint named {name}")
        values = self._history.constraints[self._shown(real)]
        n = len(values)
        answer: dict[str, Any] = {
            "name": name,
            "type": constraint.type,
            "size": constraint.size,
            "state_at_best": self._states.get(real, "unknown"),
            "history": [
                {"evaluation": index, "value": _number(values[index])}
                for index in range(max(n - MAX_ROWS, 0), n)
            ],
        }
        vector = self._vectors.get(real)
        if vector is not None and constraint.size > 1:
            chosen = [i for i in components if 0 <= i < vector.size][:MAX_COMPONENTS]
            chosen = chosen or list(range(min(vector.size, MAX_COMPONENTS)))
            violated, active = component_states(vector, constraint, self._problem)
            answer["components_at_best"] = chosen
            answer["states_at_best"] = [
                "violated" if violated[i] else "active" if active[i] else "inactive"
                for i in chosen
            ]
            if self._anonymizer is None:
                answer["values_at_best"] = _numbers(vector[chosen])
        return answer

    def list_algorithms(self) -> list[dict[str, Any]]:
        """The installed algorithms that can solve the problem."""
        return [
            {
                "name": info.name,
                "description": info.description,
                "uses_gradients": info.require_gradient,
            }
            for info in sorted(self._catalog().values(), key=lambda item: item.name)
            if not incompatibilities(info, self._problem)
        ]

    def algorithm_settings(self, name: str) -> dict[str, Any]:
        """The settings of an algorithm Claude may change, with their defaults."""
        algorithm = self._catalog().get(name)
        if algorithm is None:
            raise ValueError(f"there is no algorithm named {name}")
        fields = {
            field_name: {
                "description": field.description or "",
                "default": _default(field.default),
            }
            for field_name, field in algorithm.settings_model.model_fields.items()
            if field_name not in MANAGED_SETTINGS
        }
        answer: dict[str, Any] = {"name": name, "settings": fields}
        if name == self._problem.algo_name:
            answer["current"] = {
                key: _default(value) for key, value in self._problem.settings.items()
            }
        return answer

    def component(self, name: str) -> dict[str, Any]:
        """The inputs, outputs, description and, in ``full``, source of a component."""
        component = next(
            (item for item in self._problem.components if item.name == name), None
        )
        view = None if component is None else component_view(component, self._level)
        if view is None:
            raise ValueError(f"there is no component named {name} to show")
        return view

    def design_view(self, name: str, point: str | int = "best") -> str:
        """The map of a field of the design at a point, as text."""
        return self._view().text_map(name, point, self._entries)

    def design_indicators(self, point: str | int = "best") -> dict[str, Any]:
        """The physical indicators of the design at a point."""
        view = self._view()
        return indicators(view, view.point(point, self._entries))

    def _view(self) -> DesignView:
        if self._design is None:
            raise ValueError("the model does not describe the physics of its design")
        return self._design

    def _catalog(self) -> Mapping[str, AlgorithmInfo]:
        if self._algorithms is None:
            self._algorithms = gemseo_algorithms(self._problem.driver_kind)
        return self._algorithms

    def _variable_name(self, name: str) -> str:
        """The real name of a design variable Claude named."""
        real = name
        if self._anonymizer is not None:
            real = self._anonymizer.real_name(name) or ""
        if real not in self._offsets:
            raise ValueError(f"there is no design variable named {name}")
        return real

    def _shown(self, real_name: str) -> str:
        if self._anonymizer is None:
            return real_name
        return self._anonymizer.name(real_name)

    def _values(self, real_name: str, index: int) -> Array:
        variable = self._problem.variable(real_name)
        assert variable is not None
        start = self._offsets[real_name]
        values = np.asarray(self._entries[index][0], dtype=float)
        values = values[start : start + variable.size]
        if self._anonymizer is not None:
            values = self._anonymizer.normalize(real_name, values)
        return values


def _number(value: Any) -> float | None:
    number = float(value)
    return float(f"{number:.6g}") if np.isfinite(number) else None


def _numbers(values: Array) -> list[float | None]:
    return [_number(value) for value in values]


def _default(value: Any) -> Any:
    """A default value as JSON: simple values kept, others written as text."""
    if isinstance(value, bool | int | str) or value is None:
        return value
    if isinstance(value, float):
        return _number(value)
    return str(value)
