"""Assemblies: chains, parallel chains and MDAs of disciplines."""

from gemseo_process_builder.codegen.context import CodegenContext
from gemseo_process_builder.codegen.conversions import conversion_disciplines
from gemseo_process_builder.codegen.disciplines import Block
from gemseo_process_builder.codegen.disciplines import component_discipline
from gemseo_process_builder.codegen.literals import literal
from gemseo_process_builder.codegen.naming import to_identifier
from gemseo_process_builder.codegen.pretty import Call
from gemseo_process_builder.codegen.pretty import Expr
from gemseo_process_builder.codegen.pretty import ListExpr
from gemseo_process_builder.codegen.pretty import Raw
from gemseo_process_builder.codegen.pretty import returning
from gemseo_process_builder.codegen.pretty import string
from gemseo_process_builder.codegen.writer import Function
from gemseo_process_builder.core.graph import execution_order
from gemseo_process_builder.core.graph import strongly_connected_components
from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import ContainerNode
from gemseo_process_builder.core.model import Node


def children_disciplines(
    context: CodegenContext, container: ContainerNode, block: Block
) -> list[str]:
    """Add the lines creating the children of a container; return their variables.

    Transparent assemblies are flattened: their children are created here.
    Other assemblies and drivers are built by a function of their own.
    """
    # Imported here: nested drivers create their own children with this function.
    from gemseo_process_builder.codegen.nested import driver_discipline

    variables = []
    for child in ordered_children(context, container):
        if isinstance(child, ComponentNode):
            variables.append(component_discipline(context, child, block))
            variables.extend(conversion_disciplines(context, child, block))
        elif isinstance(child, AssemblyNode) and child.transparent:
            variables.extend(children_disciplines(context, child, block))
        elif isinstance(child, AssemblyNode):
            function = assembly_function(context, child)
            variable = context.names.allocate(to_identifier(child.name))
            block.lines.append(f"    {variable} = {function}()")
            variables.append(variable)
        else:
            variables.append(driver_discipline(context, container, child, block))
    return variables


def _successors(
    context: CodegenContext, container: ContainerNode
) -> dict[str, list[str]]:
    successors: dict[str, list[str]] = {}
    for edge in context.resolution.edges.get(container.id, []):
        successors.setdefault(edge.source, []).append(edge.target)
    return successors


def ordered_children(context: CodegenContext, container: ContainerNode) -> list[Node]:
    """The children of a container, each one after those it depends on.

    A chain runs its disciplines in the order of its list, so the order of
    the diagram is not enough, except in ``chain`` mode where the user chose it.
    """
    if isinstance(container, AssemblyNode) and container.mode == "chain":
        return list(container.children)
    order = execution_order(
        [child.id for child in container.children], _successors(context, container)
    )
    rank = {node_id: index for index, node_id in enumerate(order)}
    return sorted(container.children, key=lambda child: rank[child.id])


def loop_description(context: CodegenContext, container: ContainerNode) -> str:
    """The children in a coupling loop and the variables they exchange, or ""."""
    edges = context.resolution.edges.get(container.id, [])
    successors = _successors(context, container)
    children = [child.id for child in container.children]
    names = {child.id: child.name for child in container.children}
    for component in strongly_connected_components(children, successors):
        if len(component) > 1:
            members = set(component)
            variables = sorted(
                {
                    variable["name"]
                    for edge in edges
                    if edge.source in members and edge.target in members
                    for variable in edge.variables
                }
            )
            return (
                f"{' and '.join(names[node] for node in component)} "
                f"({', '.join(variables)})"
            )
    return ""


def process_expression(
    context: CodegenContext, container: ContainerNode, disciplines: Expr
) -> tuple[Expr, list[str]]:
    """The chain or MDA running disciplines, with the comment explaining it."""
    mode = container.mode if isinstance(container, AssemblyNode) else "mda"
    loop = loop_description(context, container)
    settings = (
        container.mda_settings
        if isinstance(container, AssemblyNode)
        else container.config.get("mda_settings", {})
    )
    if mode == "mda" or (mode == "auto" and loop):
        create_mda = context.writer.use("gemseo", "create_mda")
        comment = (
            f"An MDA solves the coupling loop between {loop}."
            if loop
            else "An MDA runs the disciplines until their coupled variables agree."
        )
        arguments = [("", string("MDAChain")), ("", disciplines)]
        arguments += [(key, literal(value)) for key, value in settings.items()]
        return Call(create_mda, arguments), [f"    # {comment}"]
    if mode == "parallel":
        chain = context.writer.use(
            "gemseo.core.chains.parallel_chain", "MDOParallelChain"
        )
        comment = "These disciplines do not depend on each other: they run in parallel."
    else:
        chain = context.writer.use("gemseo.core.chains.chain", "MDOChain")
        comment = "The disciplines run one after the other, in this order."
    return Call(chain, [("", disciplines), ("name", string(container.name))]), [
        f"    # {comment}"
    ]


def assembly_function(context: CodegenContext, assembly: ContainerNode) -> str:
    """Write the function building an assembly (or an MDA driver); return its name."""
    name = context.names.allocate(f"build_{to_identifier(assembly.name)}")
    block = Block()
    variables = children_disciplines(context, assembly, block)
    expression, comment = process_expression(
        context, assembly, ListExpr([Raw(variable) for variable in variables])
    )
    body = block.header() + block.lines + comment + returning(expression)
    discipline = context.writer.use("gemseo.core.discipline", "Discipline")
    context.writer.functions.append(
        Function(
            f"def {name}() -> {discipline}:",
            f"Create the {assembly.name} "
            f"{'assembly' if isinstance(assembly, AssemblyNode) else 'MDA'}.",
            body,
        )
    )
    return name
