"""Generation of a standalone GEMSEO script from a project (SPEC § 10).

The script reads top to bottom: docstring, imports, constants, then one short
function per step. For a model or an MDA driver:

- ``build_disciplines()`` creates the disciplines;
- ``build_process()`` combines them in a chain or an MDA;
- ``main()`` runs the process and prints its outputs.

The runner (plan 17) imports the script and calls ``build_process()`` (or
``build_scenario()`` and ``execute_scenario()`` for drivers); the
mapping from discipline names to diagram nodes is returned separately, so the
script itself contains nothing but GEMSEO code.
"""

import json
import math
import textwrap
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from gemseo_process_builder import __version__
from gemseo_process_builder.codegen.context import CodegenContext
from gemseo_process_builder.codegen.context import CodegenError
from gemseo_process_builder.codegen.design_space import design_space_function
from gemseo_process_builder.codegen.design_space import level_values
from gemseo_process_builder.codegen.disciplines import Block
from gemseo_process_builder.codegen.literals import literal
from gemseo_process_builder.codegen.naming import to_identifier
from gemseo_process_builder.codegen.pretty import LINE_LENGTH
from gemseo_process_builder.codegen.pretty import Call
from gemseo_process_builder.codegen.pretty import Expr
from gemseo_process_builder.codegen.pretty import ListExpr
from gemseo_process_builder.codegen.pretty import Raw
from gemseo_process_builder.codegen.pretty import returning
from gemseo_process_builder.codegen.scenarios import SCENARIO_KINDS
from gemseo_process_builder.codegen.scenarios import execute_function
from gemseo_process_builder.codegen.scenarios import main_function
from gemseo_process_builder.codegen.scenarios import samples_function
from gemseo_process_builder.codegen.scenarios import scenario_function
from gemseo_process_builder.codegen.structure import children_disciplines
from gemseo_process_builder.codegen.structure import process_expression
from gemseo_process_builder.codegen.writer import Function
from gemseo_process_builder.codegen.writer import ModuleWriter
from gemseo_process_builder.core.drivers import DriverConfig
from gemseo_process_builder.core.drivers import driver_config
from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import ContainerNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.resolver import PortRef
from gemseo_process_builder.core.resolver import resolve

__all__ = ["CodegenError", "GeneratedScript", "generate", "script_file_name"]

FUNCTION_NAMES = {
    "build_disciplines",
    "build_process",
    "build_design_space",
    "build_samples",
    "build_scenario",
    "execute_scenario",
    "main",
}
"""The functions of generated scripts, never used as variable names."""


@dataclass
class GeneratedScript:
    """A generated script and what the runner needs to know about it."""

    source: str
    mapping: dict[str, Any]
    """``{"target", "kind": "process" | "scenario", "disciplines", "variables"}``:
    the discipline name of each component and the component of each variable."""

    def mapping_json(self) -> str:
        """The content of the ``*.gpb-map.json`` sidecar file."""
        return json.dumps(self.mapping, indent=2, sort_keys=True) + "\n"


def script_file_name(project: Project, target_id: str) -> str:
    """A file name like ``sellar_optimizer.py``."""
    target = project.find(target_id)
    parts = [to_identifier(project.metadata.name)]
    if target is not None and target.id != project.root.id:
        parts.append(to_identifier(target.name))
    return "_".join(part for part in parts if part) + ".py"


def generate(
    project: Project,
    target_id: str | None = None,
    project_file: str = "",
    today: date | None = None,
) -> GeneratedScript:
    """Generate the script running a target of a project.

    Args:
        project: The project.
        target_id: The node to run: the root model, an assembly or a driver;
            the root by default.
        project_file: The project file name, cited in the docstring.
        today: The generation date (fixed in tests).

    Raises:
        CodegenError: When the project cannot be generated.
    """
    target = project.find(target_id or project.root.id)
    if not isinstance(target, AssemblyNode | DriverNode):
        msg = "Only the model, an assembly or a driver can be run."
        raise CodegenError(msg)
    if not target.children:
        msg = f"{target.name} is empty: add components first."
        raise CodegenError(msg)
    config = DriverConfig()
    if isinstance(target, DriverNode):
        try:
            config = driver_config(target)
        except ValidationError as error:
            msg = f"{target.name}: the driver configuration is invalid."
            raise CodegenError(msg) from error

    file_name = script_file_name(project, target.id)
    title = project.metadata.name
    if target.id != project.root.id:
        title += f": {target.name}"
    source_note = f" from {project_file}" if project_file else ""
    origin = textwrap.fill(
        f"Generated by GEMSEO Process Builder {__version__}{source_note} "
        f"on {(today or date.today()).isoformat()}.",
        LINE_LENGTH,
    )
    writer = ModuleWriter(f"{title}.\n\n{origin}\nRun it with: python {file_name}")
    context = CodegenContext(project, resolve(project), writer)
    context.names.taken.update(FUNCTION_NAMES)
    scenario = isinstance(target, DriverNode) and target.kind in SCENARIO_KINDS
    varied = set(design_variable_names(config)) if scenario else set()
    collect_typed_inputs(context, target, varied)

    block = Block()
    variables = children_disciplines(context, target, block)
    discipline = writer.use("gemseo.core.discipline", "Discipline")
    writer.functions.insert(
        0,
        Function(
            f"def build_disciplines() -> list[{discipline}]:",
            f"Create the disciplines of {target.name}.",
            block.header() + block.lines + [f"    return [{', '.join(variables)}]"],
        ),
    )
    if isinstance(target, DriverNode) and scenario:
        design_space_function(context, target, config)
        if target.kind == "parametric":
            samples_function(context, config)
        scenario_function(context, target, config)
        execute_function(context, target, config)
        main_function(context, target, config)
    else:
        process_functions(context, target)
    mapping: dict[str, Any] = {
        "target": target.id,
        "kind": "scenario" if scenario else "process",
        "disciplines": context.mapping,
        "variables": context.variables,
    }
    if isinstance(target, DriverNode) and scenario:
        mapping["progress"] = progress(target, config)
    return GeneratedScript(writer.source(), mapping)


def progress(node: DriverNode, config: DriverConfig) -> dict[str, Any]:
    """How the runner counts the progress of a scenario."""
    if node.kind == "optimization":
        return {"unit": "iteration", "total": config.algorithm.settings.get("max_iter")}
    if node.kind == "parametric":
        total = math.prod(len(level_values(level)) for level in config.levels)
        return {"unit": "sample", "total": total}
    return {"unit": "sample", "total": config.algorithm.settings.get("n_samples")}


def process_functions(context: CodegenContext, target: ContainerNode) -> None:
    """Write ``build_process()`` and ``main()`` for a target without scenario."""
    writer = context.writer
    discipline = writer.use("gemseo.core.discipline", "Discipline")
    expression, comment = process_expression(
        context, target, Raw("build_disciplines()")
    )
    writer.functions.append(
        Function(
            f"def build_process() -> {discipline}:",
            f"Combine the disciplines of {target.name} into one process.",
            comment + returning(expression),
        )
    )
    configure_logger = writer.use("gemseo", "configure_logger")
    writer.functions.append(
        Function(
            "def main() -> None:",
            "Run the process and print the results.",
            [
                f"    {configure_logger}()",
                "    process = build_process()",
                "    results = process.execute()",
                "    for name, value in sorted(results.items()):",
                '        print(f"{name} = {value}")',
            ],
        )
    )


def design_variable_names(config: DriverConfig) -> list[str]:
    """The inputs a scenario sets itself: their typed values are not used."""
    names = [variable.variable for variable in config.design_space]
    return names + [level.variable for level in config.levels]


def collect_typed_inputs(
    context: CodegenContext, target: ContainerNode, excluded: set[str]
) -> None:
    """Find the input values typed in the diagram, to set on the disciplines.

    A value typed on one port is the value of its global variable: it is set
    on every discipline using that variable. Inputs computed by a discipline
    of the target, or set by the scenario, keep no typed value.
    """
    components = [
        node for node, _ in iter_nodes(target) if isinstance(node, ComponentNode)
    ]
    ports = context.resolution.ports
    computed = {
        ports[PortRef(node.id, port.local_name, "out")].global_name
        for node in components
        for port in node.ports
        if port.direction == "out"
    }
    typed: dict[str, Expr] = {}
    users: dict[str, list[str]] = {}
    for node in components:
        for port in node.ports:
            if port.direction != "in":
                continue
            name = ports[PortRef(node.id, port.local_name, "in")].global_name
            users.setdefault(name, []).append(node.id)
            if port.default_text is not None and name not in typed:
                typed[name] = _array(context, port.default, port.default_text)
    for name, value in typed.items():
        if name not in computed and name not in excluded:
            for node_id in users[name]:
                context.typed_inputs.setdefault(node_id, {})[name] = value


def _array(context: CodegenContext, value: Any, text: str) -> Expr:
    """A NumPy array literal: GEMSEO exchanges numbers as arrays."""
    if isinstance(value, str | bool) or value is None:
        return literal(value)
    array = context.writer.use("numpy", "array")
    items = value if isinstance(value, list) else [value]
    texts = [text] if not isinstance(value, list) else [None] * len(items)
    elements = [
        literal(item, item_text) for item, item_text in zip(items, texts, strict=True)
    ]
    return Call(array, [("", ListExpr(elements))])


def write_script(script: GeneratedScript, path: Path) -> None:
    """Write a script and its mapping sidecar (``<name>.gpb-map.json``)."""
    path.write_text(script.source, encoding="utf-8", newline="\n")
    path.with_suffix(".gpb-map.json").write_text(
        script.mapping_json(), encoding="utf-8", newline="\n"
    )
