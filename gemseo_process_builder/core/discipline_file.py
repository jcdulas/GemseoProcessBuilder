"""Python files of GEMSEO disciplines created from the inspector (SPEC § 7.3).

The application writes a module with a ``Discipline`` class. Its variables are
two class attributes between markers, rewritten from the table of the
inspector::

    # >>> Variables: written by GEMSEO Process Builder from its inspector.
    INPUTS = {
        "span": array([10.0]),
        "mesh": full(100_000, 0.5),
        "stiffness": full((3, 4), 1.0),
    }
    OUTPUTS = ["area"]
    # <<< Variables

Default values are NumPy arrays of any shape and of type float, int or
complex: a few values are written one by one, larger arrays as a shape filled
with one value. The class uses GEMSEO's simple grammar, which accepts any
array and checks the data in a fraction of the time of a JSON grammar.

The rest of the file (the computation in ``_run``) belongs to the user, who
edits it in their own editor: it is never changed. Nothing here imports or
runs the file; it is only read with ``ast``.
"""

import ast
import keyword
import math
import re
from dataclasses import dataclass
from dataclasses import field
from typing import Literal

VARIABLES_START = "# >>> Variables"
VARIABLES_END = "# <<< Variables"
WRITTEN_BY = "written by GEMSEO Process Builder from its inspector."
LINE_LENGTH = 88
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DTYPES = ("float", "int", "complex")
MAX_VALUES = 20
"""Default values written one by one at most; larger arrays are filled."""

DType = Literal["float", "int", "complex"]


class DisciplineFileError(Exception):
    """A discipline file cannot be written or read; the message is for the user."""


@dataclass
class FileVariable:
    """An input, with its default value, or an output of a discipline.

    The default value of an input is either ``values`` (every element) or
    ``fill`` (one value for every element).
    """

    name: str
    direction: Literal["in", "out"]
    dtype: DType = "float"
    shape: list[int] = field(default_factory=lambda: [1])
    values: list[float] | None = None
    fill: float | None = None


def class_name_for(name: str) -> str:
    """A class name from a component name: ``my wing 2`` gives ``MyWing2``."""
    words = re.findall(r"[A-Za-z0-9]+", name)
    text = "".join(word[:1].upper() + word[1:] for word in words)
    if not text or text[0].isdigit():
        text = f"Discipline{text}"
    return text


def check_variables(variables: list[FileVariable]) -> None:
    """Refuse invalid or repeated names, bad default values, no outputs."""
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
        if variable.direction == "out":
            continue
        if variable.dtype not in DTYPES:
            msg = f"The type of {name} must be float, int or complex."
            raise DisciplineFileError(msg)
        if not variable.shape or any(size < 1 for size in variable.shape):
            msg = f"The shape of {name} must be positive sizes, like 3 or 3x4."
            raise DisciplineFileError(msg)
        if variable.values is None and variable.fill is None:
            msg = f"Give a default value to the input {name}."
            raise DisciplineFileError(msg)
        size = math.prod(variable.shape)
        if variable.values is not None and len(variable.values) > MAX_VALUES:
            msg = (
                f"{name} has more than {MAX_VALUES} values: give one value filling "
                "the array, and compute the others in the code."
            )
            raise DisciplineFileError(msg)
        if variable.values is not None and len(variable.values) != size:
            msg = (
                f"{name} has {len(variable.values)} values for {size} elements: "
                "give one value for all of them, or one per element."
            )
            raise DisciplineFileError(msg)
    if not any(variable.direction == "out" for variable in variables):
        msg = "Add at least one output."
        raise DisciplineFileError(msg)


def _number(value: float, dtype: str) -> str:
    """A number as Python code; large whole numbers get underscores."""
    if dtype == "int":
        return f"{int(value):_}" if abs(value) >= 10_000 else str(int(value))
    return repr(float(value))


def _size(size: int) -> str:
    return f"{size:_}" if size >= 10_000 else str(size)


def default_code(variable: FileVariable) -> str:
    """The default value of an input as NumPy code, like ``full(100_000, 0.5)``."""
    dtype = variable.dtype
    suffix = "" if dtype == "float" else f", dtype={dtype}"
    shape = variable.shape
    if variable.values is not None:
        numbers = ", ".join(_number(value, dtype) for value in variable.values)
        code = f"array([{numbers}]{suffix})"
        if len(shape) > 1:
            code += f".reshape({', '.join(_size(size) for size in shape)})"
        return code
    fill = _number(variable.fill or 0.0, dtype)
    if shape == [1]:
        return f"array([{fill}]{suffix})"
    dimensions = (
        _size(shape[0]) if len(shape) == 1 else f"({', '.join(map(_size, shape))})"
    )
    return f"full({dimensions}, {fill}{suffix})"


def _block(variables: list[FileVariable], indent: str = "    ") -> list[str]:
    """The lines between the markers, the markers included."""
    inputs = [variable for variable in variables if variable.direction == "in"]
    outputs = [variable for variable in variables if variable.direction == "out"]
    items = [f'"{v.name}": {default_code(v)}' for v in inputs]
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


def _numpy_names(variables: list[FileVariable]) -> set[str]:
    """The NumPy functions the block of the variables uses."""
    codes = [default_code(v) for v in variables if v.direction == "in"]
    return {name for name in ("array", "full") if any(f"{name}(" in c for c in codes)}


def new_module(
    class_name: str,
    description: str,
    variables: list[FileVariable],
    computation: list[str] | None = None,
) -> str:
    """The source of a new module with a discipline class.

    Its ``_run`` reads the inputs, computes the outputs and returns them.

    Args:
        class_name: The name of the class.
        description: What it computes, for the docstrings.
        variables: Its inputs and outputs.
        computation: The lines computing the outputs from the inputs, without
            indentation; placeholder values by default.
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
    if computation:
        run += [f"        {line}" if line else "" for line in computation]
    else:
        run.append("        # Replace these values by the computation of the outputs.")
        run += [f"        {v.name} = array([0.0])" for v in outputs]
    returned = ", ".join(f'"{v.name}": {v.name}' for v in outputs)
    numpy = ", ".join(sorted(_numpy_names(variables) | {"array", "ndarray"}))
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
        f"from numpy import {numpy}",
        "",
        "if TYPE_CHECKING:",
        "    from gemseo.typing import StrKeyMapping",
        "",
        "",
        f"class {class_name}(Discipline):",
        f'    """{summary}."""',
        "",
        "    # Any NumPy array, checked quickly: GEMSEO's JSON grammar is slow",
        "    # with large arrays and accepts only vectors of numbers.",
        "    default_grammar_type = Discipline.GrammarType.SIMPLE",
        "",
        *_block(variables),
        "",
        "    def __init__(self) -> None:",
        "        super().__init__()",
        "        self.io.input_grammar.update_from_data(self.INPUTS)",
        "        self.io.output_grammar.update_from_types(",
        "            dict.fromkeys(self.OUTPUTS, ndarray)",
        "        )",
        "        self.io.input_grammar.defaults = {",
        "            name: value.copy() for name, value in self.INPUTS.items()",
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
    """The positions of the marker lines inside a class, if both are there.

    The class goes on until the next line of the module level: a comment ending
    the class is not part of its syntax tree.
    """
    start = stop = None
    for index in range(node.lineno, len(lines)):
        line = lines[index]
        if line.strip() and not line[0].isspace() and not line.startswith("#"):
            break
        text = line.strip()
        if text.startswith(VARIABLES_START):
            start = index
        elif text.startswith(VARIABLES_END) and start is not None:
            stop = index
            break
    return (start, stop) if start is not None and stop is not None else None


def _dtype(call: ast.Call) -> DType:
    for keyword_ in call.keywords:
        value = keyword_.value
        if (
            keyword_.arg == "dtype"
            and isinstance(value, ast.Name)
            and value.id in DTYPES
        ):
            return value.id  # type: ignore[return-value]
    return "float"


def _shape(node: ast.expr) -> list[int]:
    value = ast.literal_eval(node)
    return [int(size) for size in (value if isinstance(value, tuple) else [value])]


def _input(name: str, node: ast.expr) -> FileVariable:
    """An input from its default value: a list, ``array(…)`` or ``full(…)``."""
    try:
        if isinstance(node, ast.List | ast.Tuple | ast.Constant):
            value = ast.literal_eval(node)
            values = [
                float(x)
                for x in (value if isinstance(value, list | tuple) else [value])
            ]
            return FileVariable(name, "in", "float", [len(values)], values)
        shape: list[int] | None = None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "reshape"
        ):
            # reshape(3, 4) or reshape((3, 4)).
            shape = [size for arg in node.args for size in _shape(arg)]
            node = node.func.value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            dtype = _dtype(node)
            if node.func.id == "array":
                values = [
                    complex(x).real if dtype == "complex" else float(x)
                    for x in ast.literal_eval(node.args[0])
                ]
                return FileVariable(name, "in", dtype, shape or [len(values)], values)
            if node.func.id == "full":
                fill = ast.literal_eval(node.args[1])
                return FileVariable(
                    name, "in", dtype, _shape(node.args[0]), None, float(fill)
                )
    except (ValueError, TypeError, IndexError):
        pass
    msg = (
        f"The default value of {name} is not array([…]) nor full(shape, value): "
        "edit it in the code."
    )
    raise DisciplineFileError(msg)


def read_variables(source: str, class_name: str) -> list[FileVariable] | None:
    """The variables of a class written by the application.

    Returns:
        The variables, or ``None`` for a class declaring them otherwise.
    """
    node = _class(source, class_name)
    if _markers(source.splitlines(), node) is None:
        return None
    inputs: list[FileVariable] = []
    outputs: list[str] = []
    for statement in node.body:
        if not (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            continue
        target = statement.targets[0].id
        if target == "INPUTS" and isinstance(statement.value, ast.Dict):
            for key, value in zip(
                statement.value.keys, statement.value.values, strict=True
            ):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    msg = f"The names of the INPUTS of {class_name} must be strings."
                    raise DisciplineFileError(msg)
                inputs.append(_input(key.value, value))
        elif target == "OUTPUTS":
            try:
                outputs = [str(name) for name in ast.literal_eval(statement.value)]
            except ValueError:
                msg = f"The OUTPUTS of {class_name} must be a list of names."
                raise DisciplineFileError(msg) from None
    return inputs + [FileVariable(name, "out") for name in outputs]


def _with_numpy_imports(lines: list[str], names: set[str]) -> list[str]:
    """The lines with ``from numpy import …`` importing these names too."""
    tree = ast.parse("\n".join(lines))
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom) and statement.module == "numpy":
            present = {alias.name for alias in statement.names}
            if names <= present:
                return lines
            start = statement.lineno - 1
            end = statement.end_lineno or statement.lineno
            imported = ", ".join(sorted(present | names))
            return [*lines[:start], f"from numpy import {imported}", *lines[end:]]
    last_import = max(
        (
            s.end_lineno or s.lineno
            for s in tree.body
            if isinstance(s, ast.Import | ast.ImportFrom)
        ),
        default=0,
    )
    return [
        *lines[:last_import],
        f"from numpy import {', '.join(sorted(names))}",
        *lines[last_import:],
    ]


def write_variables(source: str, class_name: str, variables: list[FileVariable]) -> str:
    """The source with the variables of a class rewritten.

    Nothing else changes, except the NumPy functions the new default values
    need, added to the imports.
    """
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
    names = _numpy_names(variables)
    if names:
        lines = _with_numpy_imports(lines, names)
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")
