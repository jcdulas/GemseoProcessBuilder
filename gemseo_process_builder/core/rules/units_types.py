"""Rules about units and variable types (SPEC § 5.5, § 5.6, § 9.1)."""

from collections.abc import Iterator

from pydantic import ValidationError

from gemseo_process_builder.core.drivers import driver_config
from gemseo_process_builder.core.graph import strongly_connected_components
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.resolver import PortRef
from gemseo_process_builder.core.units import check
from gemseo_process_builder.core.units import is_valid
from gemseo_process_builder.core.validation import Problem
from gemseo_process_builder.core.validation import ValidationContext
from gemseo_process_builder.core.validation import rule

TEXT_TYPES = {"str", "path"}


def _components(context: ValidationContext) -> dict[str, ComponentNode]:
    return {
        node.id: node
        for node, _ in iter_nodes(context.project.root)
        if isinstance(node, ComponentNode)
    }


def _pairs(
    context: ValidationContext,
) -> Iterator[tuple[str, PortRef, Port, PortRef, Port]]:
    """Every coupling from a component output to a component input.

    Yields:
        The global name, then the output and the input with their ports.
    """
    components = _components(context)
    resolution = context.resolution
    seen: set[tuple[PortRef, PortRef]] = set()
    for couplings in resolution.couplings.values():
        for name, coupling in couplings.items():
            if not coupling.producers:
                continue
            producer = resolution.component_port(coupling.producers[0])
            if producer is None or producer.direction != "out":
                continue
            output = components[producer.node].port(producer.port, "out")
            for virtual, _ in coupling.consumers:
                consumer = resolution.component_port(virtual)
                if consumer is None or consumer.node == producer.node:
                    continue
                input_ = components[consumer.node].port(consumer.port, "in")
                if output is None or input_ is None or (producer, consumer) in seen:
                    continue
                seen.add((producer, consumer))
                yield name, producer, output, consumer, input_


def _link_to(context: ValidationContext, consumer: PortRef) -> str:
    for link in context.project.links:
        if link.target.node == consumer.node and link.target.port == consumer.port:
            return link.id
    return ""


@rule("units")
def units(context: ValidationContext) -> list[Problem]:
    """Units are valid; coupled variables have compatible units (SPEC § 5.5)."""
    problems = []
    components = _components(context)
    for node in components.values():
        for port in node.ports:
            if not is_valid(port.unit):
                problems.append(
                    Problem(
                        "invalid_unit",
                        "error",
                        f"{node.name}.{port.local_name}: {port.unit!r} is not a unit.",
                        node.id,
                        port.local_name,
                    )
                )
    for name, producer, output, consumer, input_ in _pairs(context):
        result = check(output.unit, input_.unit)
        source = components[producer.node].name
        target = components[consumer.node].name
        link = _link_to(context, consumer)
        if result.status == "incompatible":
            problems.append(
                Problem(
                    "incompatible_units",
                    "error",
                    f"{name} of {source} cannot feed {target}.{consumer.port}: "
                    f"{result.message}.",
                    consumer.node,
                    consumer.port,
                    link,
                )
            )
        elif result.status == "convert":
            converted = next(
                (
                    link_.convert_units
                    for link_ in context.project.links
                    if link_.id == link
                ),
                input_.convert_units,
            )
            if converted:
                problems.append(
                    Problem(
                        "unit_conversion",
                        "warning",
                        f"{name} of {source} is converted for {target} "
                        f"({result.message}).",
                        consumer.node,
                        consumer.port,
                        link,
                    )
                )
            else:
                problems.append(
                    Problem(
                        "unit_not_converted",
                        "warning",
                        f"{name} of {source} feeds {target} without conversion, "
                        f"although the units differ ({result.message}).",
                        consumer.node,
                        consumer.port,
                        link,
                        ["enable_conversion"],
                    )
                )
        elif result.status == "missing":
            problems.append(
                Problem(
                    "unit_missing",
                    "info",
                    f"{name} from {source} to {target}: {result.message}.",
                    consumer.node,
                    consumer.port,
                    link,
                )
            )
    return problems


def _loop_variables(context: ValidationContext) -> set[str]:
    """The coupled variables solved by an MDA: those exchanged in a loop."""
    found: set[str] = set()
    for level, edges in context.resolution.edges.items():
        container = context.project.find(level)
        children = [child.id for child in getattr(container, "children", [])]
        successors: dict[str, list[str]] = {}
        for edge in edges:
            successors.setdefault(edge.source, []).append(edge.target)
        for component in strongly_connected_components(children, successors):
            members = set(component)
            if len(members) < 2:
                continue
            for edge in edges:
                if edge.source in members and edge.target in members:
                    found.update(variable["name"] for variable in edge.variables)
    return found


def _is_nd(port: Port) -> bool:
    return port.shape_known and len(port.shape) >= 2


@rule("types")
def types(context: ValidationContext) -> list[Problem]:
    """Variable types fit their use (SPEC § 5.6)."""
    problems = []
    components = _components(context)
    loops = _loop_variables(context)
    for name, producer, output, consumer, input_ in _pairs(context):
        source = components[producer.node].name
        target = components[consumer.node].name
        if output.dtype == "int" and input_.dtype == "float":
            problems.append(
                Problem(
                    "int_to_float",
                    "info",
                    f"{name}: the integer output of {source} feeds a float input "
                    f"of {target}.",
                    consumer.node,
                    consumer.port,
                )
            )
        if name not in loops:
            continue
        if output.dtype in TEXT_TYPES:
            problems.append(
                Problem(
                    "text_mda_coupling",
                    "error",
                    f"{name} holds {output.dtype} values: an MDA cannot solve a loop "
                    f"on it ({source} and {target} depend on each other).",
                    producer.node,
                    producer.port,
                )
            )
        elif _is_nd(output) and not output.flatten:
            problems.append(
                Problem(
                    "nd_mda_coupling",
                    "warning",
                    f"{name} is a {'×'.join(map(str, output.shape))} array solved "
                    "by an MDA, which handles 1-D arrays only: accept to exchange "
                    "it flattened.",
                    producer.node,
                    producer.port,
                    quick_fixes=["accept_flattening"],
                )
            )
    problems += _nd_design_variables(context, components)
    return problems


def _nd_design_variables(
    context: ValidationContext, components: dict[str, ComponentNode]
) -> list[Problem]:
    """N-D inputs set by a design space, which only holds 1-D variables."""
    problems = []
    for node, _ in iter_nodes(context.project.root):
        if not isinstance(node, DriverNode):
            continue
        try:
            config = driver_config(node)
        except ValidationError:
            continue
        names = {variable.variable for variable in config.design_space}
        names |= {level.variable for level in config.levels}
        couplings = context.resolution.couplings.get(node.id, {})
        for name in sorted(names):
            coupling = couplings.get(name)
            for virtual, _ in coupling.consumers if coupling else []:
                ref = context.resolution.component_port(virtual)
                port = components[ref.node].port(ref.port, "in") if ref else None
                if ref is None or port is None or not _is_nd(port) or port.flatten:
                    continue
                problems.append(
                    Problem(
                        "nd_design_variable",
                        "warning",
                        f"{node.name}: {name} is a {'×'.join(map(str, port.shape))} "
                        f"array of {components[ref.node].name}, but design spaces "
                        "hold 1-D vectors: accept to set it flattened.",
                        ref.node,
                        ref.port,
                        quick_fixes=["accept_flattening"],
                    )
                )
    return problems
