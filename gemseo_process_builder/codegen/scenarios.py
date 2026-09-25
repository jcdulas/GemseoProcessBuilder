"""Scenarios: optimizations, DOEs and parametric studies (SPEC § 6.2)."""

from typing import Any

from gemseo_process_builder.codegen.context import CodegenContext
from gemseo_process_builder.codegen.context import CodegenError
from gemseo_process_builder.codegen.design_space import level_values
from gemseo_process_builder.codegen.literals import literal
from gemseo_process_builder.codegen.literals import number
from gemseo_process_builder.codegen.naming import to_identifier
from gemseo_process_builder.codegen.pretty import Call
from gemseo_process_builder.codegen.pretty import Expr
from gemseo_process_builder.codegen.pretty import ListExpr
from gemseo_process_builder.codegen.pretty import Raw
from gemseo_process_builder.codegen.pretty import returning
from gemseo_process_builder.codegen.pretty import statement
from gemseo_process_builder.codegen.pretty import string
from gemseo_process_builder.codegen.structure import loop_description
from gemseo_process_builder.codegen.writer import Function
from gemseo_process_builder.core.drivers import Constraint
from gemseo_process_builder.core.drivers import DriverConfig
from gemseo_process_builder.core.drivers import algorithm_name
from gemseo_process_builder.core.drivers import formulation_name
from gemseo_process_builder.core.model import DriverNode

SCENARIO_KINDS = ("optimization", "doe", "parametric")

FORMULATION_COMMENTS = {
    "MDF": "MDF formulation: {mda} {step}.",
    "IDF": (
        "IDF formulation: the optimizer also sets the coupling variables and\n"
        "adds constraints making them consistent, so no MDA is needed."
    ),
    "DisciplinaryOpt": (
        "DisciplinaryOpt formulation: the disciplines are evaluated one after\n"
        "the other {step}."
    ),
    "BiLevel": (
        "BiLevel formulation: at each iteration, an MDA computes the coupling\n"
        "variables, each sub-optimization improves its own design variables,\n"
        "then a second MDA updates the couplings."
    ),
}


def _settings(settings: dict[str, Any]) -> list[tuple[str, Expr]]:
    return [(key, literal(value)) for key, value in settings.items()]


def scenario_class(context: CodegenContext, node: DriverNode) -> str:
    """The class of the scenario, imported for type hints."""
    if node.kind == "optimization":
        return context.writer.use("gemseo.scenarios.mdo_scenario", "MDOScenario")
    return context.writer.use("gemseo.scenarios.doe_scenario", "DOEScenario")


def objective_names(node: DriverNode, config: DriverConfig) -> list[str]:
    """The objectives; for a DOE, the first response (GEMSEO needs one)."""
    if node.kind == "optimization":
        names = [objective.variable for objective in config.objectives]
    else:
        names = config.responses[:1]
    if not names:
        what = "an objective" if node.kind == "optimization" else "a response"
        msg = f"{node.name}: choose {what} first."
        raise CodegenError(msg)
    return names


def _formulation_comment(
    context: CodegenContext, node: DriverNode, name: str
) -> list[str]:
    template = FORMULATION_COMMENTS.get(name)
    if template is None:
        return [f"    # {name} formulation."]
    loop = loop_description(context, node)
    mda = (
        f"an MDA solves the coupling loop between\n{loop}"
        if loop
        else "the disciplines are evaluated in order"
    )
    step = "at each iteration" if node.kind == "optimization" else "for each sample"
    text = template.format(mda=mda, step=step)
    return [f"    # {line}" for line in text.splitlines()]


def scenario_lines(
    context: CodegenContext,
    node: DriverNode,
    config: DriverConfig,
    disciplines: Expr,
    design_space: Expr,
) -> list[str]:
    """The lines creating ``scenario`` with its constraints and observables."""
    create = context.writer.use("gemseo", "create_scenario")
    objectives = objective_names(node, config)
    formulation = formulation_name(node, config)
    arguments: list[tuple[str, Expr]] = [
        ("", disciplines),
        (
            "",
            string(objectives[0])
            if len(objectives) == 1
            else ListExpr([string(n) for n in objectives]),
        ),
        ("", design_space),
        ("name", string(node.name)),
    ]
    if node.kind != "optimization":
        arguments.append(("scenario_type", string("DOE")))
    senses = {objective.sense for objective in config.objectives}
    if node.kind == "optimization" and senses == {"maximize"}:
        arguments.append(("maximize_objective", Raw("True")))
    elif len(senses) > 1:
        msg = f"{node.name}: GEMSEO cannot minimize and maximize objectives together."
        raise CodegenError(msg)
    arguments.append(("formulation_name", string(formulation)))
    arguments += _settings(config.formulation.settings)

    body = _formulation_comment(context, node, formulation)
    body += statement("scenario", Call(create, arguments))
    for constraint in config.constraints:
        body += _constraint_lines(context, constraint)
    extra = config.observables if node.kind == "optimization" else config.responses[1:]
    for name in extra:
        body.append(f'    scenario.add_observable("{name}")')
    return body


def scenario_function(
    context: CodegenContext, node: DriverNode, config: DriverConfig
) -> None:
    """Write ``build_scenario()``."""
    cls = scenario_class(context, node)
    body = scenario_lines(
        context, node, config, Raw("build_disciplines()"), Raw("build_design_space()")
    )
    body.append("    return scenario")
    docstring = {
        "optimization": "Set up the optimization problem.",
        "doe": "Set up the design of experiments.",
        "parametric": "Set up the parametric study.",
    }[node.kind]
    context.writer.functions.append(
        Function(f"def build_scenario() -> {cls}:", docstring, body)
    )


def _constraint_lines(context: CodegenContext, constraint: Constraint) -> list[str]:
    arguments: list[tuple[str, Expr]] = [
        ("", string(constraint.variable)),
        ("constraint_type", string(constraint.type)),
    ]
    lines: list[str] = []
    if constraint.type == "ineq" and constraint.operator == ">=":
        lines += context.explain(
            "positive_constraint",
            "GEMSEO constraints are 'output <= value' unless positive=True.",
        )
        arguments.append(("positive", Raw("True")))
    if constraint.value != 0:
        arguments.append(("value", number(constraint.value, constraint.value_text)))
    return lines + statement("", Call("scenario.add_constraint", arguments))


def samples_function(
    context: CodegenContext, config: DriverConfig, function: str = "build_samples"
) -> None:
    """Write ``build_samples()``: every combination of the levels."""
    product = context.writer.use("itertools", "product")
    array = context.writer.use("numpy", "array")
    ndarray = context.writer.use("numpy.typing", "NDArray")
    float64 = context.writer.use("numpy", "float64")
    body: list[str] = []
    names = []
    for level in config.levels:
        name = context.names.allocate(f"{to_identifier(level.variable)}_values")
        names.append(name)
        call: Expr
        if level.mode == "linspace" and level.count > 1:
            linspace = context.writer.use("numpy", "linspace")
            call = Call(
                linspace,
                [
                    ("", number(level.lower)),
                    ("", number(level.upper)),
                    ("", literal(level.count)),
                ],
            )
        else:
            call = ListExpr([number(value) for value in level_values(level)])
        body += statement(name, call)
    body += returning(
        Call(
            array,
            [("", Call("list", [("", Call(product, [("", Raw(n)) for n in names]))]))],
        )
    )
    context.writer.functions.append(
        Function(
            f"def {function}() -> {ndarray}[{float64}]:",
            "List every combination of the values, one row per evaluation.",
            body,
        )
    )


def algorithm_arguments(
    node: DriverNode, config: DriverConfig, samples: str = "build_samples"
) -> list[tuple[str, Expr]]:
    """The algorithm of a scenario and its settings, as keyword arguments."""
    if node.kind == "parametric":
        return [("algo_name", string("CustomDOE")), ("samples", Raw(f"{samples}()"))]
    settings = dict(config.algorithm.settings)
    if node.kind != "optimization" and config.execution.n_processes > 1:
        settings.setdefault("n_processes", config.execution.n_processes)
    return [("algo_name", string(algorithm_name(node, config))), *_settings(settings)]


def execute_function(
    context: CodegenContext, node: DriverNode, config: DriverConfig
) -> None:
    """Write ``execute_scenario(scenario)``."""
    cls = scenario_class(context, node)
    name = algorithm_name(node, config)
    settings = config.algorithm.settings
    arguments = algorithm_arguments(node, config)
    if node.kind == "parametric":
        docstring = "Evaluate the model for every combination of the values."
    elif node.kind == "doe":
        samples = settings.get("n_samples")
        docstring = (
            f"Evaluate the model at {samples} points chosen by {name}."
            if samples
            else f"Evaluate the model at the points chosen by {name}."
        )
    else:
        iterations = settings.get("max_iter")
        docstring = f"Run the {name} optimizer" + (
            f" for at most {iterations} iterations." if iterations else "."
        )
    context.writer.functions.append(
        Function(
            f"def execute_scenario(scenario: {cls}) -> None:",
            docstring,
            statement("", Call("scenario.execute", arguments)),
        )
    )


def main_function(
    context: CodegenContext, node: DriverNode, config: DriverConfig
) -> None:
    """Write ``main()``: run, then save the history and the results."""
    configure_logger = context.writer.use("gemseo", "configure_logger")
    path = context.writer.use("pathlib", "Path")
    body = [
        f"    {configure_logger}()",
        "    scenario = build_scenario()",
        "    execute_scenario(scenario)",
        f"    folder = {path}(__file__).parent",
    ]
    if config.execution.save_history:
        body.append('    scenario.save_optimization_history(folder / "history.h5")')
    body.append('    scenario.to_dataset().to_csv(folder / "dataset.csv")')
    what = "optimization" if node.kind == "optimization" else "study"
    context.writer.functions.append(
        Function(
            "def main() -> None:",
            f"Run the {what} and save its results next to this script.",
            body,
        )
    )
