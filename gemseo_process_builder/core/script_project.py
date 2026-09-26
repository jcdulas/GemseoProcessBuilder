"""Projects saved as GEMSEO scripts (SPEC § 4.2.2).

A project can be a Python script: the GEMSEO script the application writes,
readable and runnable on its own. What only the interface needs (positions,
units, descriptions, ids) goes to a hidden side file next to it,
``.<name>.gpb.json``, with the fingerprint of the script as written: when the
script has not changed since, the project is read from the side file;
otherwise the script is read again (``workers/script_reader.py``).

The application writes only its own functions (``build_disciplines``,
``build_scenario``…) and imports; the rest of the file is kept: functions,
classes and statements the user added. A script written by hand builds and
runs its study at the module level: those statements are replaced by the
functions of the application, its definitions are kept, and the original is
copied next to it once.
"""

import ast
import hashlib
import json
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from gemseo_process_builder.core.ids import new_id
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import Node
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.ports import USER_FIELDS

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

SIDE_FILE_VERSION = 1


def side_file(script: Path) -> Path:
    """The hidden file holding what the script cannot: ``.<name>.gpb.json``."""
    return script.with_name(f".{script.stem}.gpb.json")


def backup_file(script: Path) -> Path:
    """Where the original of a script written by hand is kept."""
    return script.with_name(f"{script.stem}.original.py")


def fingerprint(text: str) -> str:
    """The fingerprint of a script, to know whether it changed."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def side_data(project_data: dict[str, Any], script_text: str) -> str:
    """The content of the side file of a script."""
    return json.dumps(
        {
            "version": SIDE_FILE_VERSION,
            "script": fingerprint(script_text),
            "project": project_data,
        },
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )


def read_side(script: Path) -> tuple[dict[str, Any], bool] | None:
    """The project kept next to a script, and whether the script is unchanged.

    Returns:
        ``None`` without a readable side file.
    """
    path = side_file(script)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        text = script.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "project" not in data:
        return None
    return data["project"], data.get("script") == fingerprint(text)


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
    """A folder constant the application writes, like ``WORK_FOLDER = Path(…)``."""
    return (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.endswith("_FOLDER")
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


def _named_nodes(project: Project) -> dict[tuple[str, ...], Node]:
    """The nodes of a project by the names from the root down to them."""
    found: dict[tuple[str, ...], Node] = {}

    def visit(node: Node, path: tuple[str, ...]) -> None:
        found[path] = node
        for child in getattr(node, "children", []):
            visit(child, (*path, child.name))

    visit(project.root, ())
    return found


def carry_over(new: Project, old: Project) -> None:
    """Give a project read from a script what only its side file knew.

    Nodes are matched by their names from the root: they take the id,
    position, description and port units and descriptions of the old ones,
    so that runs and layout still refer to them. The runs, surrogates,
    settings and metadata of the project are kept too.
    """
    old_nodes = _named_nodes(old)
    used = {node.id for node in old_nodes.values()}
    for path, node in _named_nodes(new).items():
        previous = old_nodes.get(path)
        if previous is None or type(previous) is not type(node):
            if node.id in used:  # An id of the old project, given to another node.
                node.id = new_id("n")
            continue
        layout = old.layout.nodes.get(previous.id)
        new.layout.nodes.pop(node.id, None)
        node.id = previous.id
        if layout is not None:
            new.layout.nodes[node.id] = layout
        node.description = node.description or previous.description
        if isinstance(node, ComponentNode) and isinstance(previous, ComponentNode):
            ports = {(p.local_name, p.direction): p for p in previous.ports}
            node.ports = [
                port.model_copy(
                    update={
                        field: getattr(ports[key], field)
                        for field in USER_FIELDS
                        if getattr(ports[key], field) not in (None, "")
                    }
                )
                if (key := (port.local_name, port.direction)) in ports
                else port
                for port in node.ports
            ]
    new.runs = old.runs
    new.surrogates = old.surrogates
    new.settings = old.settings
    new.layout.levels = old.layout.levels
    new.layout.extra = old.layout.extra
    new.metadata = old.metadata.model_copy(
        update={"description": old.metadata.description or new.metadata.description}
    )
