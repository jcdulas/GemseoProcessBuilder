"""Commands fixing validation problems in one click."""

from gemseo_process_builder.core.caches import CacheSetting
from gemseo_process_builder.core.caches import cache_setting
from gemseo_process_builder.core.caches import cache_values
from gemseo_process_builder.core.commands import Command
from gemseo_process_builder.core.commands import DeleteLinks
from gemseo_process_builder.core.commands import SetLinkOptions
from gemseo_process_builder.core.commands import SetNodeProperties
from gemseo_process_builder.core.commands import SetPortOptions
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.validation import Problem

FIX_LABELS = {
    "isolate_namespace": "Isolate the variable names of this node",
    "remove_link": "Remove the link",
    "switch_to_mda": "Solve the loop with an MDA",
    "switch_to_auto": "Run the content automatically (chain or MDA)",
    "reintrospect": "Read the variables again",
    "enable_conversion": "Convert the value to the unit of the input",
    "accept_flattening": "Exchange the array as a 1-D vector",
    "one_process": "Run the evaluations of the driver in one process",
    "cache_in_memory": "Keep the executions in memory instead of a file",
}

FLATTENED_SIDE = {"nd_mda_coupling": "out", "nd_design_variable": "in"}
"""The port that accepts the flattening: the producer of a coupling, or the
input set by a design space."""


def fix_command(
    problem: Problem, fix: str, project: Project | None = None
) -> Command | None:
    """The command applying a fix, or ``None`` for fixes that are not commands.

    Args:
        problem: The problem.
        fix: The fix.
        project: The project, for the fixes changing a configuration.

    Raises:
        ValueError: When the fix is not offered for this problem.
    """
    if fix not in problem.quick_fixes:
        msg = f"The fix {fix!r} does not apply to this problem."
        raise ValueError(msg)
    if fix == "isolate_namespace":
        return SetNodeProperties(
            id=problem.node,
            values={"isolated": True},
            label_text=FIX_LABELS[fix],
        )
    if fix == "remove_link":
        return DeleteLinks(ids=[problem.link])
    if fix == "switch_to_mda":
        return SetNodeProperties(
            id=problem.node, values={"mode": "mda"}, label_text=FIX_LABELS[fix]
        )
    if fix == "switch_to_auto":
        return SetNodeProperties(
            id=problem.node, values={"mode": "auto"}, label_text=FIX_LABELS[fix]
        )
    if fix == "enable_conversion":
        if problem.link:
            return SetLinkOptions(
                id=problem.link, convert_units=True, label_text=FIX_LABELS[fix]
            )
        return SetPortOptions(
            id=problem.node,
            port=problem.port,
            direction="in",
            values={"convert_units": True},
            label_text=FIX_LABELS[fix],
        )
    if fix == "accept_flattening":
        return SetPortOptions(
            id=problem.node,
            port=problem.port,
            direction=FLATTENED_SIDE[problem.code],  # type: ignore[arg-type]
            values={"flatten": True},
            label_text=FIX_LABELS[fix],
        )
    if fix in ("one_process", "cache_in_memory") and project is not None:
        return _cache_fix(problem, fix, project)
    return None


def _cache_fix(problem: Problem, fix: str, project: Project) -> Command:
    """One process for the driver, or the cache of the node in memory."""
    if fix == "one_process":
        driver = project.find(problem.related)
        if not isinstance(driver, DriverNode):
            msg = "The driver of this problem no longer exists."
            raise ValueError(msg)
        execution = {**driver.config.get("execution", {}), "n_processes": 1}
        return SetNodeProperties(
            id=driver.id,
            values={"config": {**driver.config, "execution": execution}},
            label_text=FIX_LABELS[fix],
        )
    node = project.find(problem.node)
    setting = cache_setting(node) if node is not None else None
    if node is None or setting is None:
        msg = "The node of this problem no longer has a cache."
        raise ValueError(msg)
    memory = CacheSetting(type="memory", tolerance=setting.tolerance)
    return SetNodeProperties(
        id=node.id, values=cache_values(node, memory), label_text=FIX_LABELS[fix]
    )
