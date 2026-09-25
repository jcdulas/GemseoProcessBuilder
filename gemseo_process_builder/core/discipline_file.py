"""Python files of GEMSEO disciplines created from the inspector (SPEC § 7.3).

The application writes a module with a ``Discipline`` class. Its variables are
two class attributes between markers, rewritten from the table of the
inspector::

    # >>> Variables: written by GEMSEO Process Builder from its inspector.
    INPUTS = {"span": [10.0], "chord": [2.0]}
    OUTPUTS = ["area"]
    # <<< Variables

The rest of the file (the computation in ``_run``) belongs to the user, who
edits it in their own editor: it is never changed. Nothing here imports or
runs the file; it is only read with ``ast``.
"""

import ast
import keyword
import re
from dataclasses import dataclass
from typing import Literal

VARIABLES_START = "# >>> Variables"
VARIABLES_END = "# <<< Variables"
WRITTEN_BY = "written by GEMSEO Process Builder from its inspector."
LINE_LENGTH = 88
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DisciplineFileError(Exception):
    """A discipline file cannot be written or read; the message is for the user."""


@dataclass
class FileVariable:
    """An input (with its default value) or an output of a discipline."""

    name: str
    direction: Literal["in", "out"]
    default: list[float] | None = None
    """The default value of an input, one number per element."""


def class_name_for(name: str) -> str:
    """A class name from a component name: ``my wing 2`` gives ``MyWing2``."""
    words = re.findall(r"[A-Za-z0-9]+", name)
    text = "".join(word[:1].upper() + word[1:] for word in words)
    if not text or text[0].isdigit():
        text = f"Discipline{text}"
    return text


def check_variables(variables: list[FileVariable]) -> None:
    """Refuse invalid or repeated names, inputs without a value, no outputs."""
    seen: set[str] = set()
    for variable in variables:
        name = variable.name
        if not NAME.match(name) or keyword.iskeyword(name):
            msg = f'"{name}" is not a valid Python name: use letters, digits and _.'
            raise DisciplineFileError(msg)
        if name in seen:
            msg = f"{name} is declared twice."
            raise DisciplineFileError(msg)
        seen.add(name)
        if variable.direction == "in" and not variable.default:
            msg = f"Give a default value to the input {name}."
            raise DisciplineFileError(msg)
    if not any(variable.direction == "out" for variable in variables):
        msg = "Add at least one output."
        raise DisciplineFileError(msg)


def _number(value: float) -> str:
    return repr(float(value))


def _block(variables: list[FileVariable], indent: str = "    ") -> list[str]:
    """The lines between the markers, the markers included."""
    inputs = [variable for variable in variables if variable.direction == "in"]
    outputs = [variable for variable in variables if variable.direction == "out"]
    items = [
        f'"{v.name}": [{", ".join(_number(x) for x in v.default or [])}]'
        for v in inputs
    ]
    lines = [f"{indent}{VARIABLES_START}: {WRITTEN_BY}"]
    one_line = f"{indent}INPUTS = {{{', '.join(items)}}}"
    if len(one_line) <= LINE_LENGTH:
        lines.append(one_line)
    else:
        lines += [
            f"{indent}INPUTS = {{",
            *(f"{indent}    {item}," for item in items),
            f"{indent}}}",
        ]
    names = [f'"{v.name}"' for v in outputs]
    one_line = f"{indent}OUTPUTS = [{', '.join(names)}]"
    if len(one_line) <= LINE_LENGTH:
        lines.append(one_line)
    else:
        lines += [
            f"{indent}OUTPUTS = [",
            *(f"{indent}    {name}," for name in names),
            f"{indent}]",
        ]
    lines.append(f"{indent}{VARIABLES_END}")
    return lines


def new_module(class_name: str, description: str, variables: list[FileVariable]) -> str:
    """The source of a new module with a discipline class.

    Its ``_run`` reads the inputs and returns placeholder outputs, to be
    replaced by the computation.
    """
    check_variables(variables)
    if not NAME.match(class_name) or keyword.iskeyword(class_name):
        msg = f'"{class_name}" is not a valid class name.'
        raise DisciplineFileError(msg)
    inputs = [v for v in variables if v.direction == "in"]
    outputs = [v for v in variables if v.direction == "out"]
    summary = description.strip().rstrip(".") or f"The {class_name} discipline"
    run = [f'        {v.name} = input_data["{v.name}"]' for v in inputs]
    if run:
        run.append("")
    run.append("        # Replace these values by the computation of the outputs.")
    run += [f"        {v.name} = array([0.0])" for v in outputs]
    returned = ", ".join(f'"{v.name}": {v.name}' for v in outputs)
    lines = [
        f'"""{summary}: a GEMSEO discipline.',
        "",
        "Created with GEMSEO Process Builder. Edit the inputs and outputs in its",
        "inspector, which rewrites the block between the Variables markers; write",
        "the computation in _run.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import TYPE_CHECKING",
        "",
        "from gemseo.core.discipline import Discipline",
        "from numpy import array",
        "",
        "if TYPE_CHECKING:",
        "    from gemseo.typing import StrKeyMapping",
        "",
        "",
        f"class {class_name}(Discipline):",
        f'    """{summary}."""',
        "",
        *_block(variables),
        "",
        "    def __init__(self) -> None:",
        "        super().__init__()",
        "        self.io.input_grammar.update_from_names(self.INPUTS)",
        "        self.io.output_grammar.update_from_names(self.OUTPUTS)",
        "        self.io.input_grammar.defaults = {",
        "            name: array(value) for name, value in self.INPUTS.items()",
        "        }",
        "",
        "    def _run(self, input_data: StrKeyMapping) -> StrKeyMapping | None:",
        *run,
        f"        return {{{returned}}}",
        "",
    ]
    return "\n".join(lines)


def _class(source: str, class_name: str) -> ast.ClassDef:
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        msg = f"The file has a syntax error, line {error.lineno}: {error.msg}."
        raise DisciplineFileError(msg) from None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    msg = f"The file has no class {class_name}."
    raise DisciplineFileError(msg)


def _markers(lines: list[str], node: ast.ClassDef) -> tuple[int, int] | None:
    """The positions of the marker lines inside a class, if both are there."""
    end = node.end_lineno or len(lines)
    start = stop = None
    for index in range(node.lineno, end):
        text = lines[index].strip()
        if text.startswith(VARIABLES_START):
            start = index
        elif text.startswith(VARIABLES_END) and start is not None:
            stop = index
            break
    return (start, stop) if start is not None and stop is not None else None


def read_variables(source: str, class_name: str) -> list[FileVariable] | None:
    """The variables of a class written by the application.

    Returns:
        The variables, or ``None`` for a class declaring them otherwise.
    """
    node = _class(source, class_name)
    if _markers(source.splitlines(), node) is None:
        return None
    values: dict[str, object] = {}
    for statement in node.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id in ("INPUTS", "OUTPUTS")
        ):
            try:
                values[statement.targets[0].id] = ast.literal_eval(statement.value)
            except ValueError:
                name = statement.targets[0].id
                msg = f"The {name} of {class_name} are not plain values."
                raise DisciplineFileError(msg) from None
    inputs = values.get("INPUTS", {})
    outputs = values.get("OUTPUTS", [])
    if not isinstance(inputs, dict) or not isinstance(outputs, list):
        msg = f"INPUTS must be a dictionary and OUTPUTS a list in {class_name}."
        raise DisciplineFileError(msg)
    variables = [
        FileVariable(
            str(name),
            "in",
            [float(x) for x in (value if isinstance(value, list | tuple) else [value])],
        )
        for name, value in inputs.items()
    ]
    return variables + [FileVariable(str(name), "out") for name in outputs]


def write_variables(source: str, class_name: str, variables: list[FileVariable]) -> str:
    """The source with the variables of a class rewritten; nothing else changes."""
    check_variables(variables)
    node = _class(source, class_name)
    lines = source.splitlines()
    found = _markers(lines, node)
    if found is None:
        msg = (
            f"The variables of {class_name} are not written by the application: "
            "edit them in the code."
        )
        raise DisciplineFileError(msg)
    start, stop = found
    indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
    lines[start : stop + 1] = _block(variables, indent)
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")
