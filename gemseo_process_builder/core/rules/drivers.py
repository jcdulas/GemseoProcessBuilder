"""Rules about drivers: design space, objectives, responses, algorithm."""

from collections.abc import Iterator

from pydantic import ValidationError

from gemseo_process_builder.core.drivers import DesignVariable
from gemseo_process_builder.core.drivers import DriverConfig
from gemseo_process_builder.core.drivers import DriverVariables
from gemseo_process_builder.core.drivers import algorithm_name
from gemseo_process_builder.core.drivers import driver_config
from gemseo_process_builder.core.drivers import driver_variables
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.validation import Problem
from gemseo_process_builder.core.validation import ValidationContext
from gemseo_process_builder.core.validation import rule

TEXT_TYPES = {"str", "path"}


def _drivers(
    context: ValidationContext,
) -> Iterator[tuple[DriverNode, DriverConfig, DriverVariables]]:
    """The drivers whose configuration is valid, with the variables of their scope."""
    for node, _ in iter_nodes(context.project.root):
        if isinstance(node, DriverNode) and node.kind != "mda":
            try:
                config = driver_config(node)
            except ValidationError:
                continue  # Reported by invalid_driver_config.
            yield (
                node,
                config,
                driver_variables(context.project, context.resolution, node),
            )


@rule("invalid_driver_config")
def invalid_driver_config(context: ValidationContext) -> list[Problem]:
    """The configuration stored in the file must be readable."""
    problems = []
    for node, _ in iter_nodes(context.project.root):
        if isinstance(node, DriverNode):
            try:
                driver_config(node)
            except ValidationError as error:
                count = error.error_count()
                message = f"{node.name}: invalid configuration ({count} errors)."
                problems.append(
                    Problem("invalid_driver_config", "error", message, node.id)
                )
    return problems


@rule("design_variables")
def design_variables(context: ValidationContext) -> list[Problem]:
    """Design variables are free numeric inputs with consistent bounds."""
    problems = []
    for node, config, variables in _drivers(context):
        names = [variable.variable for variable in config.design_space]
        names += [level.variable for level in config.levels]
        for name in names:
            port = variables.inputs.get(name)
            if port is None:
                problems.append(
                    Problem(
                        "design_variable_not_free",
                        "error",
                        f"{node.name}: {name} is not a free input of the driver; "
                        "only inputs that no discipline computes can be design "
                        "variables.",
                        node.id,
                        name,
                    )
                )
            elif port.dtype in TEXT_TYPES:
                problems.append(
                    Problem(
                        "text_design_variable",
                        "error",
                        f"{node.name}: {name} holds {port.dtype} values; "
                        "it cannot be a design variable.",
                        node.id,
                        name,
                    )
                )
        for variable in config.design_space:
            problems.extend(_bound_problems(node, variable))
        for level in config.levels:
            if level.mode == "linspace" and level.lower > level.upper:
                problems.append(_bounds_problem(node, level.variable))
            if level.mode == "list" and not level.values:
                problems.append(
                    Problem(
                        "empty_levels",
                        "error",
                        f"{node.name}: {level.variable} has no values.",
                        node.id,
                        level.variable,
                    )
                )
    return problems


def _bounds_problem(node: DriverNode, name: str) -> Problem:
    return Problem(
        "inconsistent_bounds",
        "error",
        f"{node.name}: the lower bound of {name} is above its upper bound.",
        node.id,
        name,
    )


def _bound_problems(node: DriverNode, variable: DesignVariable) -> list[Problem]:
    name = variable.variable
    out_of_bounds = False
    for index in range(variable.size):
        low = variable.lower[index] if variable.lower else None
        high = variable.upper[index] if variable.upper else None
        start = variable.value[index] if variable.value else None
        if low is not None and high is not None and low > high:
            return [_bounds_problem(node, name)]
        if start is not None:
            out_of_bounds |= (low is not None and start < low) or (
                high is not None and start > high
            )
    if not out_of_bounds:
        return []
    return [
        Problem(
            "value_out_of_bounds",
            "error",
            f"{node.name}: the initial value of {name} is out of its bounds.",
            node.id,
            name,
        )
    ]


@rule("driver_outputs")
def driver_outputs(context: ValidationContext) -> list[Problem]:
    """Objectives and responses exist and are numeric outputs of the scope."""
    problems = []
    for node, config, variables in _drivers(context):
        if node.kind == "optimization" and not config.objectives:
            problems.append(
                Problem(
                    "missing_objective",
                    "error",
                    f"{node.name}: choose an objective.",
                    node.id,
                )
            )
        if node.kind in ("doe", "parametric") and not config.responses:
            problems.append(
                Problem(
                    "missing_response",
                    "error",
                    f"{node.name}: choose at least one response.",
                    node.id,
                )
            )
        names = [objective.variable for objective in config.objectives]
        names += [constraint.variable for constraint in config.constraints]
        names += config.observables + config.responses
        for name in dict.fromkeys(names):
            port = variables.outputs.get(name)
            if port is None:
                problems.append(
                    Problem(
                        "not_an_output",
                        "error",
                        f"{node.name}: no discipline of the driver computes {name}.",
                        node.id,
                        name,
                    )
                )
            elif port.dtype in TEXT_TYPES:
                problems.append(
                    Problem(
                        "text_output",
                        "error",
                        f"{node.name}: {name} holds {port.dtype} values; it cannot "
                        "be an objective, a constraint or a response.",
                        node.id,
                        name,
                    )
                )
    return problems


@rule("algorithm")
def algorithm(context: ValidationContext) -> list[Problem]:
    """The optimization algorithm handles the problem as configured."""
    known = context.algorithms.get("optimization")
    if not known:
        return []  # Not listed by the worker yet.
    problems = []
    for node, config, _ in _drivers(context):
        if node.kind != "optimization":
            continue
        name = algorithm_name(node, config)
        capabilities = known.get(name)
        if capabilities is None:
            problems.append(
                Problem(
                    "unknown_algorithm",
                    "error",
                    f"{node.name}: the algorithm {name} is not installed.",
                    node.id,
                )
            )
            continue
        for reason in incompatibilities(config, capabilities):
            problems.append(
                Problem(
                    "incompatible_algorithm",
                    "error",
                    f"{node.name}: {name} {reason}.",
                    node.id,
                    reason,
                )
            )
    return problems


def incompatibilities(config: DriverConfig, capabilities: dict[str, bool]) -> list[str]:
    """Why an optimization algorithm cannot solve a problem, if it cannot.

    The page uses the same reasons to gray out algorithms.
    """
    reasons = []
    types = {constraint.type for constraint in config.constraints}
    if "eq" in types and not capabilities.get("handle_equality_constraints"):
        reasons.append("does not handle equality constraints")
    if "ineq" in types and not capabilities.get("handle_inequality_constraints"):
        reasons.append("does not handle inequality constraints")
    if len(config.objectives) > 1 and not capabilities.get("handle_multiobjective"):
        reasons.append("does not handle several objectives")
    integers = any(variable.type == "integer" for variable in config.design_space)
    if integers and not capabilities.get("handle_integer_variables"):
        reasons.append("does not handle integer variables")
    return reasons
