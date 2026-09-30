"""What may be sent to Claude (spec § 7.1).

Three levels:

- ``full``: names, values, history, descriptions and source code;
- ``no_code``: the same without source code;
- ``anonymized``: design variables, objectives and constraints renamed ``x1``,
  ``f1``, ``g1`` (``h1`` for equalities, ``o1`` for observables); design values
  normalized to [0, 1] by the bounds the user set; functions divided by a
  fixed scale; no component, no description, no code.

In ``anonymized``, :class:`Anonymizer` keeps the mapping: decisions come back
with anonymous names and normalized values, and are translated back before
they are checked.
"""

import re
from dataclasses import replace
from typing import Any
from typing import Literal

import numpy as np

from gemseo_claude_pilot.decisions import AddSamples
from gemseo_claude_pilot.decisions import ChangeDesignSpace
from gemseo_claude_pilot.decisions import ChangeSubScenario
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.decisions import Values
from gemseo_claude_pilot.decisions import VariableChange
from gemseo_claude_pilot.guardrails import RejectedDecisionError
from gemseo_claude_pilot.snapshots import Array
from gemseo_claude_pilot.snapshots import Component
from gemseo_claude_pilot.snapshots import Constraint
from gemseo_claude_pilot.snapshots import HistorySnapshot
from gemseo_claude_pilot.snapshots import ProblemSnapshot
from gemseo_claude_pilot.snapshots import SubScenario
from gemseo_claude_pilot.snapshots import Variable
from gemseo_claude_pilot.snapshots import normalization

DataLevel = Literal["full", "no_code", "anonymized"]

DATA_LEVELS: tuple[DataLevel, ...] = ("full", "no_code", "anonymized")

_ANONYMOUS_NAME = re.compile(r"\b[xfghos]\d+\b")


def component_view(component: Component, level: DataLevel) -> dict[str, Any] | None:
    """What may be sent about a component; ``None`` in ``anonymized``."""
    if level == "anonymized":
        return None
    view: dict[str, Any] = {
        "name": component.name,
        "description": component.description,
        "inputs": list(component.inputs),
        "outputs": list(component.outputs),
    }
    if level == "full":
        view["source"] = component.source
    return view


class Anonymizer:
    """Hides the names and values of a problem, and reveals them back.

    Args:
        problem: The problem as the user set it up: its bounds normalize the
            design values for the whole run.
    """

    def __init__(self, problem: ProblemSnapshot) -> None:
        self._original = {variable.name: variable for variable in problem.variables}
        names = {
            variable.name: f"x{i}" for i, variable in enumerate(problem.variables, 1)
        }
        names[problem.objective] = "f1"
        inequalities = [item for item in problem.constraints if item.type == "ineq"]
        equalities = [item for item in problem.constraints if item.type == "eq"]
        names |= {item.name: f"g{i}" for i, item in enumerate(inequalities, 1)}
        names |= {item.name: f"h{i}" for i, item in enumerate(equalities, 1)}
        names |= {name: f"o{i}" for i, name in enumerate(problem.observables, 1)}
        names |= {sub.name: f"s{i}" for i, sub in enumerate(problem.sub_scenarios, 1)}
        self._names = names
        self._real_names = {anonymous: real for real, anonymous in names.items()}
        self._scales: dict[str, float] = {}

    def name(self, real_name: str) -> str:
        """The anonymous name of a variable or function."""
        return self._names.get(real_name, real_name)

    def real_name(self, anonymous_name: str) -> str | None:
        """The real name behind an anonymous one, if it is one."""
        return self._real_names.get(anonymous_name)

    def problem(self, problem: ProblemSnapshot) -> ProblemSnapshot:
        """The problem as Claude sees it."""
        return replace(
            problem,
            variables=tuple(self._variable(variable) for variable in problem.variables),
            objective="f1",
            standardized_objective="f1",
            constraints=tuple(
                Constraint(
                    self.name(item.name), self.name(item.name), item.type, item.size
                )
                for item in problem.constraints
            ),
            observables=tuple(self.name(name) for name in problem.observables),
            components=(),
            # Their local variables and objectives are names too: left out.
            sub_scenarios=tuple(
                SubScenario(self.name(sub.name), sub.algo_name, sub.settings)
                for sub in problem.sub_scenarios
            ),
        )

    def history(
        self, history: HistorySnapshot, problem: ProblemSnapshot
    ) -> HistorySnapshot:
        """The history as Claude sees it.

        Args:
            history: The history.
            problem: The problem as it is now: its bounds normalized the
                recent points of the history.
        """
        offset, scale = self._normalization()
        now_offset, now_scale = normalization(
            problem.lower_bounds, problem.upper_bounds
        )
        recent = (history.recent_x * now_scale + now_offset - offset) / scale
        objective_scale = self._scale("f1", history.objective)
        gradient_norm = history.gradient_norm
        if gradient_norm is not None:
            gradient_norm = gradient_norm / self._scale("@f1", gradient_norm)
        best_gradient = history.best_gradient
        if best_gradient is not None:
            best_gradient = best_gradient * scale / objective_scale
        return replace(
            history,
            objective=history.objective / objective_scale,
            violation=history.violation / self._scale("violation", history.violation),
            recent_x=recent,
            first_x=(history.first_x - offset) / scale,
            best_x=(history.best_x - offset) / scale,
            constraints={
                self.name(name): values / self._scale(self.name(name), values)
                for name, values in history.constraints.items()
            },
            gradient_norm=gradient_norm,
            best_gradient=best_gradient,
        )

    def decision(self, decision: Decision) -> Decision:
        """A decision of Claude, with real names and values.

        Raises:
            RejectedDecisionError: When it names a variable that does not exist.
        """
        action = decision.action
        if isinstance(action, ChangeDesignSpace):
            variables = [self._change(change) for change in action.variables]
            action = action.model_copy(update={"variables": variables})
        elif isinstance(action, ChangeSubScenario):
            real = self.real_name(action.scenario) or action.scenario
            action = action.model_copy(update={"scenario": real})
        elif isinstance(action, AddSamples):
            region = [self._change(change) for change in action.region]
            action = action.model_copy(update={"region": region})
        return decision.model_copy(
            update={
                "action": action,
                "diagnosis": self.reveal(decision.diagnosis),
                "rationale": self.reveal(decision.rationale),
                "expected_effect": self.reveal(decision.expected_effect),
            }
        )

    def normalize(self, real_name: str, values: Array) -> Array:
        """Values of a design variable, normalized by the bounds the user set."""
        offset, scale = normalization(*self._bounds(real_name))
        return (np.asarray(values, dtype=float) - offset) / scale

    def reveal(self, text: str) -> str:
        """A text of Claude with the real names."""
        return _ANONYMOUS_NAME.sub(
            lambda match: self._real_names.get(match[0], match[0]), text
        )

    def conceal(self, text: str) -> str:
        """A text of the user, such as a question, with the anonymous names."""
        for real in sorted(self._names, key=len, reverse=True):
            text = re.sub(
                rf"(?<![\w.]){re.escape(real)}(?![\w.])", self._names[real], text
            )
        return text

    def _variable(self, variable: Variable) -> Variable:
        offset, scale = normalization(*self._bounds(variable.name))
        value = variable.value
        return Variable(
            name=self.name(variable.name),
            size=variable.size,
            lower=(variable.lower - offset) / scale,
            upper=(variable.upper - offset) / scale,
            value=None if value is None else (value - offset) / scale,
            integer=variable.integer,
        )

    def _change(self, change: VariableChange) -> VariableChange:
        real = self.real_name(change.name)
        if real is None or real not in self._original:
            raise RejectedDecisionError(
                [f"there is no design variable named {change.name}"]
            )
        offset, scale = normalization(*self._bounds(real))
        return VariableChange(
            name=real,
            lower=_denormalize(change.lower, offset, scale),
            upper=_denormalize(change.upper, offset, scale),
            value=_denormalize(change.value, offset, scale),
        )

    def _bounds(self, real_name: str) -> tuple[Array, Array]:
        variable = self._original[real_name]
        return variable.lower, variable.upper

    def _normalization(self) -> tuple[Array, Array]:
        lower = np.concatenate([item.lower for item in self._original.values()])
        upper = np.concatenate([item.upper for item in self._original.values()])
        return normalization(lower, upper)

    def _scale(self, key: str, values: Array) -> float:
        """A fixed positive scale per quantity: its first nonzero magnitude."""
        if key not in self._scales:
            finite = np.abs(values[np.isfinite(values) & (values != 0)])
            if not finite.size:
                return 1.0
            self._scales[key] = float(finite[0])
        return self._scales[key]


def _denormalize(values: Values | None, offset: Array, scale: Array) -> Values | None:
    if values is None:
        return None
    array = np.asarray(values, dtype=float).ravel()
    if array.size == 1 and offset.size > 1:
        array = np.full(offset.size, array[0])
    if array.size != offset.size:
        return [float(item) for item in array]
    real = offset + array * scale
    return float(real[0]) if real.size == 1 else [float(item) for item in real]
