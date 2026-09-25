"""The inputs and outputs of a workflow: what its start and end circles show.

The inputs of a level are the variables its components use that nothing in it
computes, and that no driver in it sets (design variables, parameters): the
values the user gives. Its outputs are the variables computed in it that no
component in it uses (its final results), and the ones the user chose to show
(``exposed_outputs`` of the level).
"""

from dataclasses import dataclass
from dataclasses import field
from typing import Any

from gemseo_process_builder.core.drivers import driver_config
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import ContainerNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Node
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.resolver import PortRef
from gemseo_process_builder.core.resolver import Resolution


@dataclass
class WorkflowVariable:
    """An input or an output of a workflow, with the ports behind it."""

    name: str
    ports: list[PortRef] = field(default_factory=list)
    """The component ports using it (inputs) or computing it (outputs)."""

    port: Port | None = None
    """The first of these ports: its unit, shape and value."""

    final: bool = True
    """For outputs: whether no component of the level uses it."""

    def to_dict(self) -> dict[str, Any]:
        """The variable for the page."""
        port = self.port
        return {
            "name": self.name,
            "nodes": list(dict.fromkeys(ref.node for ref in self.ports)),
            "ports": [ref.__dict__ for ref in self.ports],
            "unit": port.unit if port else None,
            "value": port.default if port else None,
            "text": port.default_text if port else None,
            "final": self.final,
        }


def _components(
    level: ContainerNode,
) -> list[tuple[ComponentNode, set[str]]]:
    """The components of a level, each with the variables its drivers set."""
    found: list[tuple[ComponentNode, set[str]]] = []

    def visit(node: Node, set_by_drivers: set[str]) -> None:
        if isinstance(node, ComponentNode):
            found.append((node, set_by_drivers))
            return
        if isinstance(node, DriverNode):
            config = driver_config(node)
            set_by_drivers = set_by_drivers | {
                variable.variable for variable in config.design_space
            }
            set_by_drivers |= {level_.variable for level_ in config.levels}
        for child in node.children:
            visit(child, set_by_drivers)

    visit(level, set())
    return found


def workflow_io(
    resolution: Resolution, level: ContainerNode
) -> dict[str, list[dict[str, Any]]]:
    """The inputs and outputs of a level, as shown by its start and end."""
    inputs: dict[str, WorkflowVariable] = {}
    outputs: dict[str, WorkflowVariable] = {}
    used: set[str] = set()
    components = _components(level)
    for component, set_by_drivers in components:
        for port in component.ports:
            name = resolution.global_name(component.id, port.local_name, port.direction)
            if name is None:
                continue
            ref = PortRef(component.id, port.local_name, port.direction)
            if port.direction == "out":
                variable = outputs.setdefault(name, WorkflowVariable(name, port=port))
            else:
                used.add(name)
                if name in set_by_drivers:
                    continue
                variable = inputs.setdefault(name, WorkflowVariable(name, port=port))
            variable.ports.append(ref)
    exposed = set(level.exposed_outputs)
    for name, variable in outputs.items():
        variable.final = name not in used
    return {
        "inputs": [
            variable.to_dict()
            for name, variable in sorted(inputs.items())
            if name not in outputs
        ],
        "outputs": [
            variable.to_dict()
            for name, variable in sorted(outputs.items())
            if variable.final or name in exposed
        ],
        # The other outputs, which the user can choose to show at the end.
        "others": [
            variable.to_dict()
            for name, variable in sorted(outputs.items())
            if not variable.final and name not in exposed
        ],
    }
