"""Commands fixing validation problems in one click."""

from gemseo_process_builder.core.commands import Command
from gemseo_process_builder.core.commands import DeleteLinks
from gemseo_process_builder.core.commands import SetLinkOptions
from gemseo_process_builder.core.commands import SetNodeProperties
from gemseo_process_builder.core.commands import SetPortOptions
from gemseo_process_builder.core.validation import Problem

FIX_LABELS = {
    "isolate_namespace": "Isolate the variable names of this node",
    "remove_link": "Remove the link",
    "switch_to_mda": "Solve the loop with an MDA",
    "switch_to_auto": "Run the content automatically (chain or MDA)",
    "reintrospect": "Read the variables again",
    "enable_conversion": "Convert the value to the unit of the input",
    "accept_flattening": "Exchange the array as a 1-D vector",
}

FLATTENED_SIDE = {"nd_mda_coupling": "out", "nd_design_variable": "in"}
"""The port that accepts the flattening: the producer of a coupling, or the
input set by a design space."""


def fix_command(problem: Problem, fix: str) -> Command | None:
    """The command applying a fix, or ``None`` for fixes that are not commands.

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
    return None
