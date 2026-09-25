"""The configuration of drivers (SPEC § 6.2 and § 6.4).

A driver keeps its configuration as plain JSON data in ``DriverNode.config``,
so project files stay simple; the models below validate it and give typed
access. Every field has a default: a new driver has an empty configuration.
"""

import math
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.resolver import SCENARIO_KINDS
from gemseo_process_builder.core.resolver import PortRef
from gemseo_process_builder.core.resolver import Resolution
from gemseo_process_builder.core.resolver import is_bilevel

DRIVER_KINDS = ("mda", "doe", "optimization", "parametric")

DEFAULT_ALGORITHMS = {
    "mda": "MDAChain",
    "doe": "LHS",
    "optimization": "SLSQP",
    "parametric": "CustomDOE",
}
"""The algorithm used while the user has not chosen one."""

DEFAULT_FORMULATIONS = {
    "doe": "DisciplinaryOpt",
    "optimization": "MDF",
    "parametric": "DisciplinaryOpt",
}
"""The formulation used while the user has not chosen one (MDF needs an MDA)."""

Bound = float | None
"""A bound or a value; ``None`` means unbounded (or no initial value)."""


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DesignVariable(_Config):
    """A variable of the design space."""

    variable: str
    size: int = Field(default=1, ge=1)
    lower: list[Bound] = []
    """One bound per element; empty means unbounded."""

    upper: list[Bound] = []
    value: list[Bound] = []
    """The initial value; empty means the middle of the bounds (or the default)."""

    type: Literal["float", "integer"] = "float"
    texts: dict[str, str] = {}
    """``lower``, ``upper`` or ``value`` as typed when one value fills the vector."""

    @model_validator(mode="after")
    def _check_sizes(self) -> "DesignVariable":
        for name in ("lower", "upper", "value"):
            values = getattr(self, name)
            if values and len(values) != self.size:
                msg = (
                    f"{self.variable}: {name} has {len(values)} values "
                    f"for size {self.size}."
                )
                raise ValueError(msg)
        return self


class Objective(_Config):
    """An objective to minimize or maximize."""

    variable: str
    sense: Literal["minimize", "maximize"] = "minimize"


class Constraint(_Config):
    """A constraint ``variable <= value``, ``variable >= value`` or ``== value``."""

    variable: str
    type: Literal["eq", "ineq"] = "ineq"
    operator: Literal["<=", ">="] = "<="
    value: float = 0.0
    value_text: str | None = None


class Choice(_Config):
    """An algorithm, a formulation or an MDA, with its settings."""

    name: str = ""
    """Empty until chosen: the default of the driver kind is used."""

    settings: dict[str, Any] = {}
    """Only the settings that differ from their default."""


class Level(_Config):
    """The values taken by a variable in a parametric study."""

    variable: str
    mode: Literal["linspace", "list"] = "linspace"
    lower: float = 0.0
    upper: float = 1.0
    count: int = Field(default=3, ge=1)
    values: list[float] = []


class Execution(_Config):
    """How a driver runs."""

    n_processes: int = Field(default=1, ge=1)
    save_history: bool = True
    working_directory: str = ""


class Interface(_Config):
    """What a driver inside another node exchanges with it (SPEC § 6.3).

    GEMSEO wraps the scenario in an ``MDOScenarioAdapter``: a discipline that
    runs the whole scenario each time it is executed.
    """

    inputs: list[str] = []
    """Inputs set by the parent before each run of the scenario."""

    outputs: list[str] = []
    """Outputs read by the parent after each run: the optimum, constraints…"""

    reset_x0_before_opt: bool = False
    """Start each run from the initial design, not from the last optimum."""

    set_x0_before_opt: bool = False
    """Start each run from the design variable values set by the parent."""

    set_bounds_before_opt: bool = False
    """Take the bounds of the design variables from the parent."""

    keep_opt_history: bool = False
    """Keep the history of every run (memory consuming)."""

    @model_validator(mode="after")
    def _check_start(self) -> "Interface":
        if self.reset_x0_before_opt and self.set_x0_before_opt:
            msg = "Choose one way to start each run, not both."
            raise ValueError(msg)
        return self


ADAPTER_SETTINGS = (
    "reset_x0_before_opt",
    "set_x0_before_opt",
    "set_bounds_before_opt",
    "keep_opt_history",
)
"""The ``Interface`` fields passed to ``MDOScenarioAdapter``."""


class DriverConfig(_Config):
    """Everything a driver can be configured with; each kind uses a part of it."""

    design_space: list[DesignVariable] = []
    objectives: list[Objective] = []
    constraints: list[Constraint] = []
    observables: list[str] = []
    responses: list[str] = []
    """DOE and parametric study outputs; the first one is GEMSEO's objective."""

    algorithm: Choice = Choice()
    formulation: Choice = Choice()
    mda_settings: dict[str, Any] = {}
    """Settings of the ``MDAChain`` run by an MDA driver."""

    levels: list[Level] = []
    execution: Execution = Execution()
    interface: Interface = Interface()


CONFIG_FIELDS = tuple(DriverConfig.model_fields)

FIELD_LABELS = {
    "design_space": "Change design variables",
    "objectives": "Change objectives",
    "constraints": "Change constraints",
    "observables": "Change observables",
    "responses": "Change responses",
    "algorithm": "Change algorithm",
    "formulation": "Change formulation",
    "mda_settings": "Change MDA settings",
    "levels": "Change parametric levels",
    "execution": "Change execution options",
    "interface": "Change interface",
}


def driver_config(node: DriverNode) -> DriverConfig:
    """The typed configuration of a driver.

    Raises:
        pydantic.ValidationError: When the stored configuration is invalid.
    """
    return DriverConfig.model_validate(node.config)


def config_data(config: DriverConfig) -> dict[str, Any]:
    """The configuration as stored in the project: defaults left out."""
    return config.model_dump(mode="json", exclude_defaults=True)


def algorithm_name(node: DriverNode, config: DriverConfig) -> str:
    """The algorithm used by a driver: the chosen one or the default."""
    return config.algorithm.name or DEFAULT_ALGORITHMS.get(node.kind, "")


def formulation_name(node: DriverNode, config: DriverConfig) -> str:
    """The formulation used by a driver: the chosen one or the default."""
    return config.formulation.name or DEFAULT_FORMULATIONS.get(node.kind, "")


def response_names(node: DriverNode, config: DriverConfig) -> list[str]:
    """The outputs a driver computes: objectives first, then the others."""
    if node.kind in ("doe", "parametric"):
        return list(config.responses)
    names = [objective.variable for objective in config.objectives]
    names += [constraint.variable for constraint in config.constraints]
    return names + list(config.observables)


def variable_roles(node: DriverNode, config: DriverConfig) -> dict[str, list[str]]:
    """The roles of each variable in a driver, like ``{"x": ["design variable"]}``."""
    roles: dict[str, list[str]] = {}

    def add(name: str, role: str) -> None:
        roles.setdefault(name, []).append(role)

    for variable in config.design_space:
        add(variable.variable, "design variable")
    for level in config.levels:
        add(level.variable, "design variable")
    for objective in config.objectives:
        add(objective.variable, "objective")
    for constraint in config.constraints:
        add(constraint.variable, "constraint")
    for name in config.observables:
        add(name, "observable")
    for name in config.responses:
        add(name, "response")
    return roles


@dataclass
class DriverVariables:
    """The variables a driver can use, by global name, with a port describing each."""

    inputs: dict[str, Port] = field(default_factory=dict)
    """The free inputs of the driver scope: candidates for design variables."""

    outputs: dict[str, Port] = field(default_factory=dict)
    """The outputs computed in the scope: objectives, constraints, responses."""

    couplings: dict[str, Port] = field(default_factory=dict)
    """The outputs also used as inputs in the scope: IDF design variables."""


def driver_variables(
    project: Project, resolution: Resolution, driver: DriverNode
) -> DriverVariables:
    """The free inputs and the outputs of a driver's scope."""
    components = {
        node.id: node
        for node, _ in iter_nodes(driver)
        if isinstance(node, ComponentNode)
    }

    def port_of(ref: PortRef) -> Port | None:
        """The port of a component, or of a component inside a nested driver."""
        found = resolution.component_port(ref)
        if found is None or found.node not in components:
            return None
        return components[found.node].port(found.port, found.direction)  # type: ignore[arg-type]

    variables = DriverVariables()
    couplings = resolution.couplings.get(driver.id, {})
    for name in resolution.free_inputs.get(driver.id, []):
        coupling = couplings.get(name)
        if coupling and coupling.consumers:
            port = port_of(coupling.consumers[0][0])
            if port is not None:
                variables.inputs[name] = port
    for name, coupling in sorted(couplings.items()):
        if coupling.producers:
            port = port_of(coupling.producers[0])
            if port is not None:
                variables.outputs[name] = port
                if coupling.consumers:
                    variables.couplings[name] = port
    return variables


def is_nested(project: Project, node: DriverNode) -> bool:
    """Whether a driver runs inside another node: a driver or an assembly.

    Drivers placed directly in the model are studies of their own.
    """
    parent = project.parent_of(node.id)
    return parent is not None and parent.id != project.root.id


def is_bilevel_sub_scenario(project: Project, node: DriverNode) -> bool:
    """Whether BiLevel chooses what a driver exchanges with its parent."""
    return node.kind in SCENARIO_KINDS and is_bilevel(project.parent_of(node.id))


def uses_idf(node: DriverNode, config: DriverConfig) -> bool:
    """Whether the optimizer also sets the coupling variables (IDF)."""
    return node.kind == "optimization" and formulation_name(node, config) == "IDF"


def idf_couplings(config: DriverConfig, variables: DriverVariables) -> list[str]:
    """The coupling variables that IDF needs in the design space.

    With ``include_weak_coupling_targets=False``, GEMSEO only needs those in a
    loop; they are not checked then.
    """
    if config.formulation.settings.get("include_weak_coupling_targets") is False:
        return []
    return sorted(variables.couplings)


ROLE_FIELDS = {
    "design_variable": "design_space",
    "level": "levels",
    "objective": "objectives",
    "constraint": "constraints",
    "observable": "observables",
    "response": "responses",
}
"""The configuration field holding each role."""

ROLES_BY_KIND = {
    "optimization": ("design_variable", "objective", "constraint", "observable"),
    "doe": ("design_variable", "response"),
    "parametric": ("level", "response"),
}
"""The roles a variable can take in each kind of driver."""

INPUT_ROLES = {"design_variable", "level"}


def _numbers(value: Any, size: int) -> list[Bound]:
    """The port default as a list of ``size`` numbers, or ``[]``."""
    values = value if isinstance(value, list) else [value]
    if len(values) != size or not all(
        isinstance(item, int | float) and not isinstance(item, bool) for item in values
    ):
        return []
    return [float(item) for item in values]


def with_role(
    config: DriverConfig, role: str, name: str, port: Port
) -> tuple[str, Any] | None:
    """The field to change to give a variable a role, or ``None`` if it has it.

    Returns:
        The field name and its new value, for ``SetDriverConfig``.
    """
    field_name = ROLE_FIELDS[role]
    current = getattr(config, field_name)
    names = [item if isinstance(item, str) else item.variable for item in current]
    if name in names:
        return None
    size = math.prod(port.shape) if port.shape else 1
    entry: Any
    if role == "design_variable":
        entry = DesignVariable(
            variable=name,
            size=size,
            value=_numbers(port.default, size),
            type="integer" if port.dtype == "int" else "float",
        )
    elif role == "level":
        # Around the default value: from half of it to one and a half times it.
        default = _numbers(port.default, 1)
        middle = (default[0] or 0.0) if default else 0.0
        low, high = sorted((middle * 0.5, middle * 1.5)) if middle else (0.0, 1.0)
        entry = Level(variable=name, lower=low, upper=high)
    elif role == "objective":
        entry = Objective(variable=name)
    elif role == "constraint":
        entry = Constraint(variable=name)
    else:
        entry = name
    items = [*current, entry]
    return field_name, [
        item if isinstance(item, str) else item.model_dump(mode="json")
        for item in items
    ]
