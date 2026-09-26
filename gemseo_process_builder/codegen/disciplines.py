"""Creation of one discipline per component."""

import textwrap
from pathlib import Path
from typing import Any

from gemseo_process_builder.codegen.context import CodegenContext
from gemseo_process_builder.codegen.context import CodegenError
from gemseo_process_builder.codegen.context import LocalImport
from gemseo_process_builder.codegen.conversions import is_wrapped
from gemseo_process_builder.codegen.conversions import wrap_reshapes
from gemseo_process_builder.codegen.literals import literal
from gemseo_process_builder.codegen.naming import to_identifier
from gemseo_process_builder.codegen.pretty import Call
from gemseo_process_builder.codegen.pretty import DictExpr
from gemseo_process_builder.codegen.pretty import Raw
from gemseo_process_builder.codegen.pretty import Text
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
    own = context.own_file
    path = config.get("module_path")
    if path and own is not None and Path(path).resolve() == own.resolve():
        return str(name)  # Defined in this very script.
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
                (string(output), Text(formula))
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
    elif node.kind == "executable":
        discipline_name = _executable(context, node, variable, block)
    elif node.kind == "surrogate":
        discipline_name = _surrogate(context, node, variable, block)
    else:
        msg = f"{node.name}: {node.kind} components cannot be generated yet."
        raise CodegenError(msg)
    context.mapping[node.id] = discipline_name
    context.variables[variable] = node.id
    _remap(context, node, variable, block)
    _set_typed_inputs(context, node, variable, block)
    wrap_reshapes(context, node, variable, block)
    return variable


def _surrogate(
    context: CodegenContext, node: ComponentNode, variable: str, block: Block
) -> str:
    """A surrogate discipline, from the regression model pickled by the wizard."""
    model_path = node.config.get("model_path")
    if not model_path:
        msg = f"{node.name}: build its surrogate first (Build surrogate wizard)."
        raise CodegenError(msg)
    constant = context.path_constant(Path(model_path), "MODEL")
    from_pickle = context.writer.use("gemseo", "from_pickle")
    surrogate = context.writer.use(
        "gemseo.disciplines.surrogate", "SurrogateDiscipline"
    )
    block.lines.extend(
        context.explain(
            "surrogate",
            "A surrogate is a regression model trained on the results of a DOE:\n"
            "fast to evaluate, and accurate inside the ranges it was trained on.",
        )
    )
    if node.config.get("summary"):
        summary = f"{node.name}: {node.config['summary']}."
        block.lines.extend(f"    # {line}" for line in textwrap.wrap(summary, 74))
    call = Call(surrogate, [("", Call(from_pickle, [("", Raw(constant))]))])
    block.lines.extend(statement(variable, call))
    block.lines.append(f'    {variable}.name = "{node.name}"')
    return node.name


def _executable(
    context: CodegenContext, node: ComponentNode, variable: str, block: Block
) -> str:
    """Add the lines creating an executable wrapper; return its discipline name."""
    from gemseo_process_builder.runtime.spec import ExecutableSpec
    from gemseo_process_builder.runtime.spec import load_descriptor
    from gemseo_process_builder.runtime.spec import spec_data

    executable = context.writer.use(
        "gemseo_process_builder.runtime.executable", "ExecutableDiscipline"
    )
    config = node.config
    try:
        if config.get("descriptor_path"):
            path = Path(config["descriptor_path"])
            spec_name = load_descriptor(path)[0].name if path.is_file() else node.name
            constant = context.path_constant(path, "WRAPPER")
            block.lines.append(
                f"    # {node.name} runs an external code described by its wrapper."
            )
            call = Call(f"{executable}.from_descriptor", [("", Raw(constant))])
        else:
            spec = ExecutableSpec.model_validate(config.get("spec") or {})
            spec_name = spec.name
            spec_class = context.writer.use(
                "gemseo_process_builder.runtime.spec", "ExecutableSpec"
            )
            data = spec_data(spec)
            arguments: list[tuple[str, Any]] = [
                (
                    "",
                    Call(
                        spec_class,
                        [(key, literal(value)) for key, value in data.items()],
                    ),
                )
            ]
            if config.get("base_folder_path"):
                folder = context.path_constant(
                    Path(config["base_folder_path"]), "FOLDER"
                )
                arguments.append(("base_folder", Raw(folder)))
            block.lines.append(f"    # {node.name} runs an external code.")
            call = Call(executable, arguments)
    except ValueError as error:
        msg = f"{node.name}: {error}"
        raise CodegenError(msg) from None
    block.lines.extend(statement(variable, call))
    if node.name != spec_name:
        block.lines.append(f'    {variable}.name = "{node.name}"')
    block.lines.extend(
        context.explain(
            "executable_jacobian",
            "External codes give no derivatives: they are approximated by finite\n"
            "differences.",
        )
    )
    block.lines.append(f"    {variable}.set_jacobian_approximation()")
    return node.name


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
        ref = PortRef(node.id, port.local_name, port.direction)
        # A converted or reshaped value has a name of its own.
        name = context.exchanges.names.get(
            ref, context.resolution.ports[ref].global_name
        )
        mappings[port.direction].append((name, port.local_name))
        if name != port.local_name:
            renamed.append((port, name))
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
    # A wrapping chain approximates the derivatives of the whole (vectors only).
    if any(port.direction == "in" for port, _ in renamed) and not is_wrapped(
        context, node
    ):
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
