"""What the driver editor needs to know: ``driver.*`` methods."""

import math
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ValidationError

from gemseo_process_builder.app.api_algorithms import AlgorithmService
from gemseo_process_builder.app.api_algorithms import KindParams
from gemseo_process_builder.app.api_resolve import ResolutionService
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.core.commands import CommandError
from gemseo_process_builder.core.commands import SetDriverConfig
from gemseo_process_builder.core.drivers import INPUT_ROLES
from gemseo_process_builder.core.drivers import ROLE_FIELDS
from gemseo_process_builder.core.drivers import ROLES_BY_KIND
from gemseo_process_builder.core.drivers import DriverConfig
from gemseo_process_builder.core.drivers import driver_config
from gemseo_process_builder.core.drivers import driver_variables
from gemseo_process_builder.core.drivers import variable_roles
from gemseo_process_builder.core.drivers import with_role
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.resolver import PortRef
from gemseo_process_builder.core.rules.drivers import incompatibilities


class DriverParams(BaseModel):
    """Parameters holding a driver id."""

    id: str


class RoleParams(BaseModel):
    """Parameters of ``driver.assignRole``."""

    node: str
    port: str
    direction: Literal["in", "out"]
    role: str


class DriverAlgorithmsParams(BaseModel):
    """Parameters of ``driver.algorithms``."""

    id: str
    kind: str


def _describe(name: str, port: Port) -> dict[str, Any]:
    return {
        "name": name,
        "dtype": port.dtype,
        "size": math.prod(port.shape) if port.shape else 1,
        "default": port.default,
        "unit": port.unit,
    }


class DriverService:
    """Answer the driver editor from the project, the resolution and the worker."""

    def __init__(
        self,
        session: ProjectSession,
        bridge: Bridge,
        resolution: ResolutionService,
        algorithms: AlgorithmService,
    ) -> None:
        self.session = session
        self.bridge = bridge
        self.resolution = resolution
        self.algorithms = algorithms

    def _driver(self, node_id: str) -> tuple[DriverNode, DriverConfig]:
        node = self.session.project.find(node_id)
        if not isinstance(node, DriverNode):
            raise BridgeError(ErrorCode.NOT_FOUND, "This driver no longer exists.")
        try:
            return node, driver_config(node)
        except ValidationError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None

    def variables(self, params: DriverParams) -> dict[str, Any]:
        """The free inputs and outputs of a driver, and their roles."""
        node, config = self._driver(params.id)
        variables = driver_variables(
            self.session.project, self.resolution.current(), node
        )
        return {
            "inputs": [_describe(n, p) for n, p in sorted(variables.inputs.items())],
            "outputs": [_describe(n, p) for n, p in variables.outputs.items()],
            "couplings": [_describe(n, p) for n, p in variables.couplings.items()],
            "roles": variable_roles(node, config),
        }

    def algorithms_for(self, params: DriverAlgorithmsParams) -> list[dict[str, Any]]:
        """The algorithms of a kind, with why each cannot be used, if it cannot."""
        _, config = self._driver(params.id)
        items = self.algorithms.list_algorithms(KindParams(kind=params.kind))
        if params.kind != "optimization":
            return [{**item, "reasons": []} for item in items]
        return [
            {**item, "reasons": incompatibilities(config, item["capabilities"])}
            for item in items
        ]

    def port_roles(self) -> dict[str, list[str]]:
        """The roles of component ports in their driver, by ``node/direction/port``."""
        project = self.session.project
        resolution = self.resolution.current()
        roles: dict[str, list[str]] = {}
        for node, _ in iter_nodes(project.root):
            if not isinstance(node, DriverNode) or node.kind == "mda":
                continue
            try:
                by_name = variable_roles(node, driver_config(node))
            except ValidationError:
                continue
            for ref, resolved in resolution.ports.items():
                if resolved.scope != node.id:
                    continue
                inputs = ref.direction == "in"
                found = [
                    role
                    for role in by_name.get(resolved.global_name, [])
                    if (role == "design variable") == inputs
                ]
                if found:
                    roles[f"{ref.node}/{ref.direction}/{ref.port}"] = found
        return roles

    def assign_role(self, params: RoleParams) -> dict[str, Any]:
        """Give a port a role in its driver (``driver.assignRole``).

        Returns:
            The driver id and the editor tab showing the role.
        """
        project = self.session.project
        resolution = self.resolution.current()
        ref = PortRef(params.node, params.port, params.direction)
        resolved = resolution.ports.get(ref)
        component = project.find(params.node)
        if resolved is None or not isinstance(component, ComponentNode):
            raise BridgeError(ErrorCode.NOT_FOUND, "This variable no longer exists.")
        driver, config = self._driver(resolved.scope)
        port = component.port(params.port, params.direction)
        if (
            port is None
            or params.role not in ROLES_BY_KIND.get(driver.kind, ())
            or (params.role in INPUT_ROLES) != (params.direction == "in")
        ):
            raise BridgeError(ErrorCode.INVALID_PARAMS, "This role is not possible.")
        change = with_role(config, params.role, resolved.global_name, port)
        if change is not None:
            field, value = change
            try:
                self.session.document.execute(
                    SetDriverConfig(id=driver.id, field=field, value=value)
                )
            except CommandError as error:
                raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        return {"driver": driver.id, "field": ROLE_FIELDS[params.role]}

    def register(self) -> None:
        """Register the ``driver.*`` methods."""
        registry = self.bridge.registry
        registry.add("driver.variables", self.variables)
        registry.add("driver.portRoles", self.port_roles)
        registry.add("driver.assignRole", self.assign_role)
        registry.add("driver.algorithms", self.algorithms_for, background=True)
