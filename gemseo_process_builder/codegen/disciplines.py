"""Creation of one discipline per component."""

from pathlib import Path
from typing import Any

from gemseo_process_builder.codegen.context import CodegenContext
from gemseo_process_builder.codegen.context import CodegenError
from gemseo_process_builder.codegen.context import LocalImport
from gemseo_process_builder.codegen.literals import literal
from gemseo_process_builder.codegen.naming import to_identifier
from gemseo_process_builder.codegen.pretty import Call
from gemseo_process_builder.codegen.pretty import DictExpr
from gemseo_process_builder.codegen.pretty import Raw
from gemseo_process_builder.codegen.pretty import statement
from gemseo_process_builder.codegen.pretty import string
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.resolver import PortRef


class Block:
    """Lines of a generated function, with the local imports they need."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.local_imports: list[LocalImport] = []

    def header(self) -> list[str]:
        """The lines importing project modules, to put first in the function."""
        lines: list[str] = []
        folders = sorted({item.folder_constant for item in self.local_imports})
        if folders:
            lines.append(
                "    # The modules of this project are imported from their folder."
            )
            lines.extend(f"    sys.path.insert(0, str({folder}))" for folder in folders)
            seen = set()
            for item in self.local_imports:
                if (item.module, item.name) not in seen:
                    seen.add((item.module, item.name))
                    lines.append(f"    from {item.module} import {item.name}")
            lines.append("")
        return lines


def _imported(
    context: CodegenContext, block: Block, config: dict[str, Any], key: str
) -> str:
    """The name of the configured class or function, imported as needed."""
    name = config.get(key)
    if not name:
        msg = f"No {key} is selected."
        raise CodegenError(msg)
    if config.get("module"):
        return context.writer.use(config["module"], name)
    if config.get("module_path"):
        context.writer.use_module("sys")
        block.local_imports.append(
            context.local_import(Path(config["module_path"]), name)
        )
        return str(name)
    msg = "No module is selected."
    raise CodegenError(msg)


def component_discipline(
    context: CodegenContext, node: ComponentNode, block: Block
) -> str:
    """Add the lines creating a component's discipline; return its variable."""
    variable = context.names.allocate(to_identifier(node.name))
    config = node.config
    if node.kind == "analytic":
        analytic = context.writer.use(
            "gemseo.disciplines.analytic", "AnalyticDiscipline"
        )
        expressions = DictExpr(
            [
                (string(output), string(formula))
                for output, formula in config.get("expressions", {}).items()
            ]
        )
        call = Call(analytic, [("", expressions), ("name", string(node.name))])
        block.lines.extend(statement(variable, call))
        discipline_name = node.name
    elif node.kind == "python_function":
        auto_py = context.writer.use("gemseo.disciplines.auto_py", "AutoPyDiscipline")
        function = _imported(context, block, config, "function")
        arguments: list[tuple[str, Any]] = [("", Raw(function))]
        if node.name != function:
            arguments.append(("name", string(node.name)))
        block.lines.extend(statement(variable, Call(auto_py, arguments)))
        discipline_name = node.name
    elif node.kind == "python_class":
        cls = _imported(context, block, config, "class")
        init_args = config.get("init_args") or {}
        call = Call(cls, [(key, literal(value)) for key, value in init_args.items()])
        block.lines.extend(statement(variable, call))
        discipline_name = cls
        if node.name != cls:
            block.lines.append(f'    {variable}.name = "{node.name}"')
            discipline_name = node.name
    else:
        msg = f"{node.name}: {node.kind} components cannot be generated yet."
        raise CodegenError(msg)
    context.mapping[node.id] = discipline_name
    context.variables[variable] = node.id
    _remap(context, node, variable, block)
    _set_typed_inputs(context, node, variable, block)
    return variable


def _set_typed_inputs(
    context: CodegenContext, node: ComponentNode, variable: str, block: Block
) -> None:
    """Replace default input values by those typed in the diagram."""
    values = context.typed_inputs.get(node.id)
    if not values:
        return
    block.lines.extend(
        context.explain(
            "typed_inputs",
            "The values typed in the diagram replace the default input values.",
        )
    )
    items = DictExpr([(string(name), value) for name, value in values.items()])
    update = Call(f"{variable}.default_input_data.update", [("", items)])
    block.lines.extend(statement("", update))


def _remap(
    context: CodegenContext, node: ComponentNode, variable: str, block: Block
) -> None:
    """Rename the variables whose global name differs from the local one."""
    mappings: dict[str, list[tuple[str, str]]] = {"in": [], "out": []}
    renamed = []
    for port in node.ports:
        resolved = context.resolution.ports[
            PortRef(node.id, port.local_name, port.direction)
        ]
        mappings[port.direction].append((resolved.global_name, port.local_name))
        if resolved.global_name != port.local_name:
            renamed.append((port, resolved.global_name))
    if not renamed:
        return
    remapping = context.writer.use(
        "gemseo.disciplines.remapping", "RemappingDiscipline"
    )
    block.lines.extend(
        context.explain(
            "remapping",
            "RemappingDiscipline gives variables the names used by the other\n"
            "disciplines; it lists every variable, renamed or not.",
        )
    )
    details = ", ".join(f"{port.local_name} as {name}" for port, name in renamed)
    block.lines.append(f"    # {node.name} exchanges {details}.")
    call = Call(
        remapping,
        [
            ("", Raw(variable)),
            ("input_mapping", _mapping(mappings["in"])),
            ("output_mapping", _mapping(mappings["out"])),
        ],
    )
    block.lines.extend(statement(variable, call))
    if any(port.direction == "in" for port, _ in renamed):
        block.lines.extend(
            context.explain(
                "remapping_jacobian",
                "GEMSEO 6 cannot differentiate a discipline whose inputs are renamed:\n"
                "its derivatives are approximated by finite differences.",
            )
        )
        block.lines.append(f"    {variable}.set_jacobian_approximation()")


def _mapping(pairs: list[tuple[str, str]]) -> DictExpr:
    return DictExpr([(string(new), string(old)) for new, old in pairs])
