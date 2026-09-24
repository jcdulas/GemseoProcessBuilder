"""Rules about the structure of the model: couplings, links, components."""

from pydantic import ValidationError

from gemseo_process_builder.core.compat import incompatibility
from gemseo_process_builder.core.drivers import driver_config
from gemseo_process_builder.core.drivers import response_names
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.validation import Problem
from gemseo_process_builder.core.validation import ValidationContext
from gemseo_process_builder.core.validation import rule

QUICK_FIXES = {
    "duplicate_producer": ["isolate_namespace"],
    "multiple_explicit_links": ["remove_link"],
    "link_to_missing_port": ["remove_link"],
    "loop_in_chain": ["switch_to_mda"],
    "dependency_in_parallel": ["switch_to_auto"],
}


def _components(context: ValidationContext) -> dict[str, ComponentNode]:
    return {
        node.id: node
        for node, _ in iter_nodes(context.project.root)
        if isinstance(node, ComponentNode)
    }


@rule("resolver")
def resolver_issues(context: ValidationContext) -> list[Problem]:
    """Problems found while resolving the couplings."""
    return [
        Problem(
            issue.code,
            "error",
            issue.message,
            issue.node,
            issue.port,
            issue.link,
            list(QUICK_FIXES.get(issue.code, [])),
        )
        for issue in context.resolution.issues
    ]


@rule("coupling_types")
def coupling_types(context: ValidationContext) -> list[Problem]:
    """A coupled output must fit the inputs it feeds (type and size)."""
    components = _components(context)
    problems = []
    for couplings in context.resolution.couplings.values():
        for name, coupling in couplings.items():
            if not coupling.producers:
                continue
            producer = coupling.producers[0]
            output = components[producer.node].port(producer.port, "out")
            for consumer, _ in coupling.consumers:
                input_ = components[consumer.node].port(consumer.port, "in")
                if output is None or input_ is None or consumer.node == producer.node:
                    continue
                reason = incompatibility(output, input_)
                if reason:
                    problems.append(
                        Problem(
                            "incompatible_coupling",
                            "error",
                            f"{name} of {components[producer.node].name} cannot feed "
                            f"{components[consumer.node].name}.{consumer.port}: "
                            f"{reason}.",
                            consumer.node,
                            consumer.port,
                        )
                    )
    return problems


@rule("components")
def component_problems(context: ValidationContext) -> list[Problem]:
    """Components whose variables cannot be read, or lost a used variable."""
    problems = []
    for node in _components(context).values():
        error = context.component_errors.get(node.id)
        if error:
            problems.append(
                Problem(
                    "introspection_failed",
                    "error",
                    f"The variables of {node.name} cannot be read: {error}",
                    node.id,
                    quick_fixes=["reintrospect"],
                )
            )
        for port in node.ports:
            if port.missing:
                problems.append(
                    Problem(
                        "missing_port",
                        "error",
                        f"{node.name} has no {port.direction}put {port.local_name} "
                        "any more, but a link still uses it.",
                        node.id,
                        port.local_name,
                        quick_fixes=["reintrospect"],
                    )
                )
    return problems


@rule("free_inputs")
def free_inputs_without_default(context: ValidationContext) -> list[Problem]:
    """A free input needs a value: its default, or a design variable later."""
    components = _components(context)
    problems = []
    for scope, names in context.resolution.free_inputs.items():
        couplings = context.resolution.couplings.get(scope, {})
        for name in names:
            for consumer, _ in couplings[name].consumers:
                node = components[consumer.node]
                port = node.port(consumer.port, "in")
                if port is not None and port.default is None and port.shape_known:
                    problems.append(
                        Problem(
                            "free_input_without_default",
                            "warning",
                            f"{node.name}.{consumer.port} has no default value and no "
                            "component computes it.",
                            node.id,
                            consumer.port,
                        )
                    )
    return problems


def _driver_outputs(context: ValidationContext, scope: str) -> set[str]:
    """The outputs a driver looks at (objectives, constraints, responses…)."""
    driver = context.project.find(scope)
    if not isinstance(driver, DriverNode):
        return set()
    try:
        return set(response_names(driver, driver_config(driver)))
    except ValidationError:
        return set()


@rule("unused_outputs")
def unused_outputs(context: ValidationContext) -> list[Problem]:
    """Outputs used by nothing (only reported when the option is on)."""
    if not context.options.get("show_unused_outputs", True):
        return []
    components = _components(context)
    problems = []
    for scope, couplings in context.resolution.couplings.items():
        used = _driver_outputs(context, scope)
        for name, coupling in couplings.items():
            if coupling.consumers or name in used:
                continue
            for producer in coupling.producers:
                node = components[producer.node]
                problems.append(
                    Problem(
                        "unused_output",
                        "info",
                        f"{name} computed by {node.name} is not used.",
                        node.id,
                        producer.port,
                    )
                )
    return problems
