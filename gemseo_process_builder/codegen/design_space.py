"""The design space of a scenario: one ``add_variable`` per design variable."""

from gemseo_process_builder.codegen.context import CodegenContext
from gemseo_process_builder.codegen.context import CodegenError
from gemseo_process_builder.codegen.literals import literal
from gemseo_process_builder.codegen.literals import number
from gemseo_process_builder.codegen.pretty import Call
from gemseo_process_builder.codegen.pretty import Expr
from gemseo_process_builder.codegen.pretty import ListExpr
from gemseo_process_builder.codegen.pretty import statement
from gemseo_process_builder.codegen.pretty import string
from gemseo_process_builder.codegen.writer import Function
from gemseo_process_builder.core.drivers import DesignVariable
from gemseo_process_builder.core.drivers import DriverConfig
from gemseo_process_builder.core.drivers import Level
from gemseo_process_builder.core.model import DriverNode


def vector(values: list[float | None], text: str | None, missing: float) -> Expr | None:
    """A bound or a value: a number when all elements are equal, else a list.

    Args:
        values: One value per element; ``None`` for no bound.
        text: The value as typed when one value fills the vector.
        missing: The value written for ``None`` (an infinite bound).

    Returns:
        ``None`` when there is nothing to write (no bound at all).
    """
    if not values or all(value is None for value in values):
        return None
    filled = [missing if value is None else value for value in values]
    if all(value == filled[0] for value in filled):
        return number(filled[0], text)
    return ListExpr([number(value) for value in filled])


def add_variable(variable: DesignVariable) -> Call:
    """The ``add_variable`` call of a design variable."""
    arguments: list[tuple[str, Expr]] = [("", string(variable.variable))]
    if variable.size > 1:
        arguments.append(("size", literal(variable.size)))
    if variable.type == "integer":
        arguments.append(("type_", string("integer")))
    for keyword, values, missing in (
        ("lower_bound", variable.lower, -float("inf")),
        ("upper_bound", variable.upper, float("inf")),
        ("value", variable.value, 0.0),
    ):
        key = keyword.removesuffix("_bound")
        expression = vector(values, variable.texts.get(key), missing)
        if expression is not None:
            arguments.append((keyword, expression))
    return Call("design_space.add_variable", arguments)


def design_variables(node: DriverNode, config: DriverConfig) -> list[DesignVariable]:
    """The design variables; for a parametric study, one per varied variable."""
    if node.kind != "parametric":
        return config.design_space
    variables = []
    for level in config.levels:
        values = level_values(level)
        if not values:
            msg = f"{node.name}: {level.variable} has no values."
            raise CodegenError(msg)
        variables.append(
            DesignVariable(
                variable=level.variable, lower=[min(values)], upper=[max(values)]
            )
        )
    return variables


def level_values(level: Level) -> list[float]:
    """The values taken by a variable of a parametric study."""
    if level.mode == "list":
        return level.values
    if level.count < 2:
        return [level.lower]
    step = (level.upper - level.lower) / (level.count - 1)
    return [level.lower + index * step for index in range(level.count)]


def design_space_function(
    context: CodegenContext, node: DriverNode, config: DriverConfig
) -> None:
    """Write ``build_design_space()``."""
    create = context.writer.use("gemseo", "create_design_space")
    design_space = context.writer.use("gemseo.algos.design_space", "DesignSpace")
    body = [f"    design_space = {create}()"]
    for variable in design_variables(node, config):
        body.extend(statement("", add_variable(variable)))
    body.append("    return design_space")
    docstring = (
        "Define the variables the study makes vary, with their bounds."
        if node.kind != "optimization"
        else "Define the variables the optimizer is allowed to change."
    )
    context.writer.functions.append(
        Function(f"def build_design_space() -> {design_space}:", docstring, body)
    )
