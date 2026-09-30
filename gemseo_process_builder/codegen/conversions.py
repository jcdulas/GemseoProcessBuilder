"""Unit conversions and 1-D exchanges between disciplines (SPEC § 5.5, § 5.6).

- A value going from an output in one unit to an input in another goes
  through a conversion discipline (``LinearCombination``: ``factor * value +
  offset``) placed after its producer; the consumer reads the converted name.
- An N-D array accepted as flattened is exchanged as a 1-D vector, since
  GEMSEO's MDAs and design spaces handle 1-D arrays only: the component is
  wrapped in a chain that reshapes its inputs and flattens its outputs.
"""

import math
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

from gemseo_process_builder.codegen.literals import literal
from gemseo_process_builder.codegen.literals import number
from gemseo_process_builder.codegen.naming import to_identifier
from gemseo_process_builder.codegen.pretty import Call
from gemseo_process_builder.codegen.pretty import DictExpr
from gemseo_process_builder.codegen.pretty import Expr
from gemseo_process_builder.codegen.pretty import ListExpr
from gemseo_process_builder.codegen.pretty import Raw
from gemseo_process_builder.codegen.pretty import statement
from gemseo_process_builder.codegen.pretty import string
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import ContainerNode
from gemseo_process_builder.core.model import Link
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.resolver import PortRef
from gemseo_process_builder.core.resolver import Resolution
from gemseo_process_builder.core.units import check

if TYPE_CHECKING:
    from gemseo_process_builder.codegen.context import CodegenContext
    from gemseo_process_builder.codegen.disciplines import Block

RESHAPE_CLASS = '''class Reshape(Discipline):
    """Pass a variable on with another shape.

    GEMSEO's MDAs and design spaces handle 1-D arrays: matrices are exchanged
    as vectors, and reshaped for the disciplines using them.
    """

    def __init__(
        self,
        input_name: str,
        output_name: str,
        input_shape: list[int],
        output_shape: list[int],
        default: NDArray[float64] | None = None,
    ) -> None:
        super().__init__(name=f"reshape_{output_name}")
        self.io.input_grammar.update_from_data({input_name: zeros(input_shape)})
        self.io.output_grammar.update_from_data({output_name: zeros(output_shape)})
        if default is not None:
            self.default_input_data = {input_name: default.reshape(input_shape)}
        self.input_name = input_name
        self.output_name = output_name
        self.output_shape = output_shape

    def _run(self, input_data: StrKeyMapping) -> StrKeyMapping:
        value = input_data[self.input_name]
        return {self.output_name: value.reshape(self.output_shape)}'''


@dataclass
class Conversion:
    """A value converted from one unit to another for its consumers."""

    name: str
    """The global name of the value, in the unit of its producer."""

    converted: str
    """The global name of the converted value."""

    factor: float
    offset: float
    size: int
    source_unit: str
    target_unit: str


@dataclass
class ReshapeStep:
    """A variable reshaped before a component, or flattened after it."""

    input_name: str
    output_name: str
    input_shape: tuple[int, ...]
    output_shape: tuple[int, ...]


@dataclass
class Exchanges:
    """What the generated script changes between the disciplines."""

    names: dict[PortRef, str] = field(default_factory=dict)
    """The global name used by a port instead of its resolved one."""

    conversions: dict[str, list[Conversion]] = field(default_factory=dict)
    """The conversions to add after each producer, by node id."""

    before: dict[str, list[ReshapeStep]] = field(default_factory=dict)
    """The inputs to reshape before each component, by node id."""

    after: dict[str, list[ReshapeStep]] = field(default_factory=dict)
    """The outputs to flatten after each component, by node id."""


def _size(port: Port) -> int:
    return math.prod(port.shape) if port.shape else 1


def _is_nd(port: Port) -> bool:
    return port.shape_known and len(port.shape) >= 2


def _converts(consumer: PortRef, port: Port, links: list[Link]) -> bool:
    """Whether a consumer accepts converted values (its link's option, or its own)."""
    for link in links:
        if link.target.node == consumer.node and link.target.port == consumer.port:
            return bool(link.convert_units)
    return port.convert_units


def plan_exchanges(
    target: ContainerNode, resolution: Resolution, links: list[Link], taken: set[str]
) -> Exchanges:
    """The conversions and reshapes of the components of a target.

    Args:
        target: What the script runs.
        resolution: The resolution of the project.
        links: The explicit links of the project.
        taken: The global names in use; new names are added.
    """
    components = {
        node.id: node
        for node, _ in iter_nodes(target)
        if isinstance(node, ComponentNode)
    }
    exchanges = Exchanges()

    def unique(name: str) -> str:
        candidate, index = name, 1
        while candidate in taken:
            index += 1
            candidate = f"{name}_{index}"
        taken.add(candidate)
        return candidate

    conversions: dict[tuple[PortRef, str], Conversion] = {}
    for couplings in resolution.couplings.values():
        for name, coupling in couplings.items():
            producer = (
                resolution.component_port(coupling.producers[0])
                if coupling.producers
                else None
            )
            output = None
            if producer is not None and producer.node in components:
                output = components[producer.node].port(producer.port, "out")
            if (
                output is not None
                and producer is not None
                and _is_nd(output)
                and output.flatten
                and producer not in exchanges.names
            ):
                shape = tuple(output.shape)
                matrix = unique(f"{to_identifier(name)}_{'x'.join(map(str, shape))}")
                exchanges.names[producer] = matrix
                exchanges.after.setdefault(producer.node, []).append(
                    ReshapeStep(matrix, name, shape, (_size(output),))
                )
            for virtual, _ in coupling.consumers:
                consumer = resolution.component_port(virtual)
                if consumer is None or consumer.node not in components:
                    continue
                input_ = components[consumer.node].port(consumer.port, "in")
                if input_ is None or consumer in exchanges.names:
                    continue
                read = name
                if output is not None and producer is not None:
                    unit = check(output.unit, input_.unit)
                    if unit.status == "convert" and _converts(consumer, input_, links):
                        key = (producer, str(input_.unit))
                        if key not in conversions:
                            conversion = Conversion(
                                name=name,
                                converted=unique(
                                    f"{to_identifier(name)}_{to_identifier(str(input_.unit))}"
                                ),
                                factor=unit.factor,
                                offset=unit.offset,
                                size=_size(output),
                                source_unit=str(output.unit),
                                target_unit=str(input_.unit),
                            )
                            conversions[key] = conversion
                            exchanges.conversions.setdefault(producer.node, []).append(
                                conversion
                            )
                        read = conversions[key].converted
                flattened = input_.flatten or bool(output and output.flatten)
                if _is_nd(input_) and flattened:
                    shaped = unique(
                        f"{to_identifier(name)}_{to_identifier(components[consumer.node].name)}"
                    )
                    exchanges.before.setdefault(consumer.node, []).append(
                        ReshapeStep(read, shaped, (_size(input_),), tuple(input_.shape))
                    )
                    read = shaped
                if read != name:
                    exchanges.names[consumer] = read
    return exchanges


def conversion_disciplines(
    context: "CodegenContext", node: ComponentNode, block: "Block"
) -> list[str]:
    """Add the conversions of a component's outputs; return their variables."""
    variables = []
    for conversion in context.exchanges.conversions.get(node.id, []):
        linear = context.writer.use(
            "gemseo.disciplines.linear_combination", "LinearCombination"
        )
        variable = context.names.allocate(
            to_identifier(
                f"convert_{conversion.name}_{conversion.source_unit}_to_{conversion.target_unit}"
            )
        )
        block.lines.extend(
            context.explain(
                "unit_conversion",
                "A conversion discipline passes a value on in the unit its users\n"
                "expect: converted = factor * value + offset.",
            )
        )
        block.lines.append(
            f"    # {node.name} gives {conversion.name} in {conversion.source_unit}, "
            f"used in {conversion.target_unit}."
        )
        arguments: list[tuple[str, Expr]] = [
            ("input_names", ListExpr([string(conversion.name)])),
            ("output_name", string(conversion.converted)),
            (
                "input_coefficients",
                DictExpr([(string(conversion.name), number(conversion.factor))]),
            ),
        ]
        if conversion.offset:
            arguments.append(("offset", number(conversion.offset)))
        if conversion.size > 1:
            arguments.append(("input_size", literal(conversion.size)))
        block.lines.extend(statement(variable, Call(linear, arguments)))
        block.lines.append(f'    {variable}.name = "{variable}"')
        variables.append(variable)
    return variables


def is_wrapped(context: "CodegenContext", node: ComponentNode) -> bool:
    """Whether a component exchanges arrays reshaped by a wrapping chain."""
    exchanges = context.exchanges
    return bool(exchanges.before.get(node.id) or exchanges.after.get(node.id))


def wrap_reshapes(
    context: "CodegenContext", node: ComponentNode, variable: str, block: "Block"
) -> None:
    """Wrap a component in a chain reshaping its N-D inputs and outputs."""
    if not is_wrapped(context, node):
        return
    writer = context.writer
    if RESHAPE_CLASS not in writer.classes:
        writer.use("gemseo.core.discipline", "Discipline")
        writer.use("gemseo.typing", "StrKeyMapping")
        writer.use("numpy", "zeros")
        writer.use("numpy", "float64")
        writer.use("numpy.typing", "NDArray")
        writer.classes.append(RESHAPE_CLASS)
    chain = writer.use("gemseo.core.chains.chain", "MDOChain")

    def step(item: ReshapeStep, default: bool = False) -> Call:
        arguments: list[tuple[str, Expr]] = [
            ("", string(item.input_name)),
            ("", string(item.output_name)),
            ("", literal(list(item.input_shape))),
            ("", literal(list(item.output_shape))),
        ]
        if default:
            # The vector starts from the default value of the matrix.
            arguments.append(
                (
                    "default",
                    Raw(f'{variable}.default_input_data.get("{item.output_name}")'),
                )
            )
        return Call("Reshape", arguments)

    names = [item.output_name for item in context.exchanges.before.get(node.id, [])]
    names += [item.input_name for item in context.exchanges.after.get(node.id, [])]
    block.lines.append(
        f"    # {node.name} uses arrays ({', '.join(names)}) that GEMSEO exchanges as "
        "vectors:"
    )
    block.lines.append(
        "    # its inputs are reshaped before it and its outputs flattened after it."
    )
    members: list[Expr] = [
        step(item, default=True) for item in context.exchanges.before.get(node.id, [])
    ]
    members.append(Raw(variable))
    members += [step(item) for item in context.exchanges.after.get(node.id, [])]
    call = Call(
        chain, [("", ListExpr(members)), ("name", string(f"{node.name}_vectors"))]
    )
    block.lines.extend(statement(variable, call))
    block.lines.extend(
        context.explain(
            "vectors_jacobian",
            "Finite differences on the vectors: GEMSEO cannot differentiate\n"
            "through the reshaping.",
        )
    )
    block.lines.append(f"    {variable}.set_jacobian_approximation()")
