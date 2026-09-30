"""Rules about drivers inside other nodes and the BiLevel formulation (SPEC § 6.3)."""

from pydantic import ValidationError

from gemseo_process_builder.core.drivers import driver_config
from gemseo_process_builder.core.drivers import driver_variables
from gemseo_process_builder.core.drivers import is_bilevel_sub_scenario
from gemseo_process_builder.core.drivers import is_nested
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.resolver import SCENARIO_KINDS
from gemseo_process_builder.core.resolver import is_bilevel
from gemseo_process_builder.core.validation import Problem
from gemseo_process_builder.core.validation import ValidationContext
from gemseo_process_builder.core.validation import rule


def _scenarios(context: ValidationContext) -> list[DriverNode]:
    return [
        node
        for node, _ in iter_nodes(context.project.root)
        if isinstance(node, DriverNode) and node.kind in SCENARIO_KINDS
    ]


@rule("nested_interface")
def nested_interface(context: ValidationContext) -> list[Problem]:
    """A nested driver gives results back, from inputs its parent can set."""
    project = context.project
    problems = []
    for node in _scenarios(context):
        if not is_nested(project, node) or is_bilevel_sub_scenario(project, node):
            continue
        try:
            interface = driver_config(node).interface
        except ValidationError:
            continue  # Reported by invalid_driver_config.
        if not interface.outputs:
            problems.append(
                Problem(
                    "nested_without_outputs",
                    "error",
                    f"{node.name} runs inside another node: choose the results "
                    "it gives back in its Interface tab.",
                    node.id,
                )
            )
        free = set(context.resolution.free_inputs.get(node.id, []))
        for name in interface.inputs:
            if name not in free:
                problems.append(
                    Problem(
                        "exposed_input_not_free",
                        "error",
                        f"{node.name}: {name} cannot be set from outside; only "
                        "inputs that no discipline of the driver computes can.",
                        node.id,
                        name,
                    )
                )
        variables = driver_variables(project, context.resolution, node)
        known = set(variables.outputs) | free
        for name in interface.outputs:
            if name not in known:
                problems.append(
                    Problem(
                        "exposed_output_unknown",
                        "error",
                        f"{node.name}: no discipline of the driver computes {name}.",
                        node.id,
                        name,
                    )
                )
    return problems


@rule("bilevel")
def bilevel(context: ValidationContext) -> list[Problem]:
    """A BiLevel optimization drives sub-optimizations on their own variables."""
    problems = []
    for node in _scenarios(context):
        if not is_bilevel(node):
            continue
        subs = [
            child
            for child in node.children
            if isinstance(child, DriverNode) and child.kind in SCENARIO_KINDS
        ]
        if not subs:
            problems.append(
                Problem(
                    "bilevel_without_sub_scenarios",
                    "error",
                    f"{node.name} uses the BiLevel formulation: put the "
                    "sub-optimizations of the disciplines inside it.",
                    node.id,
                )
            )
            continue
        try:
            system = {v.variable for v in driver_config(node).design_space}
        except ValidationError:
            continue
        for sub in subs:
            try:
                local = {v.variable for v in driver_config(sub).design_space}
            except ValidationError:
                continue
            for name in sorted(system & local):
                problems.append(
                    Problem(
                        "bilevel_shared_design_variable",
                        "warning",
                        f"{name} is a design variable of both {node.name} and "
                        f"{sub.name}: BiLevel expects the system to set the shared "
                        "variables and each sub-optimization its own ones.",
                        sub.id,
                        name,
                    )
                )
    return problems
