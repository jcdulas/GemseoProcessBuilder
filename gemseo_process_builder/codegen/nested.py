"""Drivers inside other nodes (SPEC § 6.3).

- A scenario inside an assembly or another driver becomes a discipline through
  ``MDOScenarioAdapter``, built by ``build_<name>_adapter()``.
- The sub-scenarios of a BiLevel optimization are given as they are: the
  BiLevel formulation wraps them itself.
- An MDA driver becomes an ``MDAChain``, like an assembly in ``mda`` mode.
"""

from pydantic import ValidationError

from gemseo_process_builder.codegen.context import CodegenContext
from gemseo_process_builder.codegen.context import CodegenError
from gemseo_process_builder.codegen.design_space import add_variable
from gemseo_process_builder.codegen.design_space import design_variables
from gemseo_process_builder.codegen.disciplines import Block
from gemseo_process_builder.codegen.naming import to_identifier
from gemseo_process_builder.codegen.pretty import Call
from gemseo_process_builder.codegen.pretty import Expr
from gemseo_process_builder.codegen.pretty import ListExpr
from gemseo_process_builder.codegen.pretty import Raw
from gemseo_process_builder.codegen.pretty import returning
from gemseo_process_builder.codegen.pretty import statement
from gemseo_process_builder.codegen.pretty import string
from gemseo_process_builder.codegen.scenarios import algorithm_arguments
from gemseo_process_builder.codegen.scenarios import samples_function
from gemseo_process_builder.codegen.scenarios import scenario_class
from gemseo_process_builder.codegen.scenarios import scenario_lines
from gemseo_process_builder.codegen.structure import assembly_function
from gemseo_process_builder.codegen.structure import children_disciplines
from gemseo_process_builder.codegen.writer import Function
from gemseo_process_builder.core.drivers import ADAPTER_SETTINGS
from gemseo_process_builder.core.drivers import DriverConfig
from gemseo_process_builder.core.drivers import driver_config
from gemseo_process_builder.core.model import ContainerNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.resolver import is_bilevel

KIND_NAMES = {
    "optimization": "optimization",
    "doe": "design of experiments",
    "parametric": "parametric study",
}


def adapter_name(node: DriverNode) -> str:
    """The name GEMSEO gives the adapter of a scenario (for the runner)."""
    return f"{node.name}_adapter"


def _config(node: DriverNode) -> DriverConfig:
    try:
        return driver_config(node)
    except ValidationError as error:
        msg = f"{node.name}: the driver configuration is invalid."
        raise CodegenError(msg) from error


def driver_discipline(
    context: CodegenContext, parent: ContainerNode, node: DriverNode, block: Block
) -> str:
    """Add the line creating a driver inside ``parent``; return its variable."""
    if node.kind == "mda":
        function = assembly_function(context, node)
    elif is_bilevel(parent):
        function = scenario_function(
            context, node, f"a sub-optimization of {parent.name}"
        )
    else:
        function = adapter_function(context, node, parent)
    variable = context.names.allocate(to_identifier(node.name))
    block.lines.append(f"    {variable} = {function}()")
    context.variables[variable] = node.id
    context.functions[function] = node.id
    if node.kind != "mda":
        context.mapping[node.id] = adapter_name(node)
        context.scenarios[node.id] = node.name
    if node.kind != "mda" and is_bilevel(parent):
        context.scenario_variables.add(variable)
    return variable


def scenario_function(context: CodegenContext, node: DriverNode, role: str) -> str:
    """Write ``build_<name>_scenario()`` for a nested scenario; return its name."""
    config = _config(node)
    identifier = to_identifier(node.name)
    name = context.names.allocate(f"build_{identifier}_scenario")
    samples = ""
    if node.kind == "parametric":
        samples = context.names.allocate(f"build_{identifier}_samples")
        samples_function(context, config, samples)
    block = Block()
    variables = children_disciplines(context, node, block)
    create = context.writer.use("gemseo", "create_design_space")
    body = block.header() + block.lines + [f"    design_space = {create}()"]
    for variable in design_variables(node, config):
        body += statement("", add_variable(variable))
    disciplines = ListExpr([Raw(variable) for variable in variables])
    body += scenario_lines(context, node, config, disciplines, Raw("design_space"))
    body += context.explain(
        "set_algorithm",
        "A nested scenario runs with the algorithm set here each time its\n"
        "parent executes it.",
    )
    body += statement(
        "", Call("scenario.set_algorithm", algorithm_arguments(node, config, samples))
    )
    body.append("    return scenario")
    cls = scenario_class(context, node)
    context.functions[name] = node.id
    context.writer.functions.append(
        Function(
            f"def {name}() -> {cls}:",
            f"Set up {node.name}, {role}.",
            body,
        )
    )
    return name


def adapter_function(
    context: CodegenContext, node: DriverNode, parent: ContainerNode
) -> str:
    """Write ``build_<name>_adapter()``; return its name."""
    config = _config(node)
    interface = config.interface
    kind = KIND_NAMES[node.kind]
    name = context.names.allocate(f"build_{to_identifier(node.name)}_adapter")
    # The adapter comes before the scenario it wraps: the script reads top-down.
    position = len(context.writer.functions)
    scenario = scenario_function(context, node, f"the {kind} run by {parent.name}")
    adapter = context.writer.use(
        "gemseo.disciplines.scenario_adapters.mdo_scenario_adapter",
        "MDOScenarioAdapter",
    )
    arguments: list[tuple[str, Expr]] = [
        ("", Raw(f"{scenario}()")),
        ("", ListExpr([string(input_name) for input_name in interface.inputs])),
        ("", ListExpr([string(output_name) for output_name in interface.outputs])),
    ]
    arguments += [
        (setting, Raw("True"))
        for setting in ADAPTER_SETTINGS
        if getattr(interface, setting)
    ]
    body = [
        f"    # The adapter runs the whole {kind} each time it is executed:",
        "    # it sets the inputs listed first, then gives back the outputs listed",
        "    # second.",
    ]
    body += returning(Call(adapter, arguments))
    context.writer.functions.insert(
        position,
        Function(
            f"def {name}() -> {adapter}:",
            f"Wrap {node.name} into a discipline of {parent.name}.",
            body,
        ),
    )
    return name
