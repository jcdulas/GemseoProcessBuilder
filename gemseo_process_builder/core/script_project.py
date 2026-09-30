"""Projects saved as GEMSEO scripts (SPEC § 4.2.2).

A project is a Python script: the GEMSEO script the application writes,
readable and runnable on its own. Nothing else is saved: opening the script
reads it again (``workers/script_reader.py``) and lays the diagram out.

The application writes only its own functions (``build_disciplines``,
``build_scenario``…) and imports; the rest of the file is kept: functions,
classes and statements the user added. A script written by hand builds and
runs its study at the module level: those statements are replaced by the
functions of the application, its definitions are kept, and the original is
copied next to it once.
"""

import ast
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

MANAGED_FUNCTIONS = frozenset(
    {
        "build_disciplines",
        "build_design_space",
        "build_samples",
        "build_scenario",
        "execute_scenario",
        "build_process",
        "main",
    }
)
"""The functions the application writes, rewritten at each save."""

PATH_CONSTANTS = ("_FOLDER", "_WRAPPER", "_MODEL")
"""The endings of the path constants the application writes."""


def backup_file(script: Path) -> Path:
    """Where the original of a script written by hand is kept."""
    return script.with_name(f"{script.stem}.original.py")


@dataclass
class Merged:
    """A script written by the application, with the code of the user."""

    source: str
    kept: list[str] = field(default_factory=list)
    """What was kept of the previous file (names of definitions)."""

    replaced: bool = False
    """Whether statements of a script written by hand were replaced: its
    original is to be copied first."""


def _managed(tree: ast.Module) -> bool:
    """Whether a file has the structure the application writes."""
    return any(
        isinstance(node, ast.FunctionDef) and node.name in MANAGED_FUNCTIONS
        for node in tree.body
    )


def _is_main_guard(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
    )


def _is_docstring(node: ast.stmt, index: int) -> bool:
    return (
        index == 0
        and isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _generated_constant(node: ast.stmt) -> bool:
    """A path constant the application writes, like ``WORK_FOLDER = Path(…)``."""
    return (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.endswith(PATH_CONSTANTS)
    )


def _segment(lines: list[str], node: ast.stmt) -> list[str]:
    """The lines of a statement, with its decorators and the comments above it."""
    start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
    start -= 1
    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1
    return lines[start : node.end_lineno or node.lineno]


def merge_script(generated: str, existing: str | None) -> Merged:
    """The generated script with the code the user added to the previous file.

    Args:
        generated: The script the application writes.
        existing: The file it replaces, if any.
    """
    if not existing:
        return Merged(generated)
    try:
        tree = ast.parse(existing)
    except SyntaxError:
        return Merged(generated, replaced=True)
    managed = _managed(tree)
    lines = existing.splitlines()
    generated_lines = set(generated.splitlines())
    imports: list[str] = []
    kept: list[list[str]] = []
    names: list[str] = []
    replaced = False
    for index, node in enumerate(tree.body):
        if _is_docstring(node, index) or _is_main_guard(node):
            continue
        if isinstance(node, ast.Import | ast.ImportFrom):
            text = _segment(lines, node)
            if not all(line in generated_lines for line in text):
                imports += text
            continue
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if node.name in MANAGED_FUNCTIONS:
                replaced |= not managed
                continue
            kept.append(_segment(lines, node))
            names.append(node.name)
            continue
        if managed and not _generated_constant(node):
            kept.append(_segment(lines, node))
            continue
        if not managed:
            # A statement of a script written by hand: it built or ran the
            # study, which the functions of the application now do.
            replaced = True
    if not imports and not kept:
        return Merged(generated, replaced=replaced)
    return Merged(_insert(generated, imports, kept), names, replaced)


def _insert(generated: str, imports: list[str], kept: list[list[str]]) -> str:
    """The generated script with the kept imports and code.

    The imports go after the generated ones, the code before the functions of
    the application.
    """
    tree = ast.parse(generated)
    lines = generated.splitlines()
    last_import = max(
        (
            node.end_lineno or node.lineno
            for node in tree.body
            if isinstance(node, ast.Import | ast.ImportFrom)
        ),
        default=0,
    )
    first_function = min(
        (node.lineno for node in tree.body if isinstance(node, ast.FunctionDef)),
        default=len(lines) + 1,
    )
    before = lines[:last_import]
    between = lines[last_import : first_function - 1]
    after = lines[first_function - 1 :]
    while between and not between[-1].strip():
        between.pop()
    body: list[str] = []
    for block in kept:
        body += ["", "", *block]
    return "\n".join([*before, *imports, *between, *body, "", "", *after]) + "\n"
