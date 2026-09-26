"""What belongs to a project but is not its script (SPEC § 4.2.3).

Next to its script, the user only sees the script. The autosave, the lock,
the runs and the surrogates of a project live in a folder of the user data
directory of the application, one per project file: ``projects/<name>-<key>/``.
The folder holds ``project.json``: the path of the file, which finds the
folder, the fingerprint of the script and the tree of its model, which find it
again when the script was moved.

The name of a folder never changes: the scripts refer to their surrogates in
it.
"""

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from gemseo_process_builder.core.atomic_write import write_text_atomically
from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Node
from gemseo_process_builder.core.model import Project

PROJECTS = "projects"
UNTITLED = "untitled"
AUTOSAVE = "autosave.json"
LOCK = "lock"
RUNS = "runs"
SURROGATES = "surrogates"
ORIGIN = "project.json"


def _same_file(path: str, project: Path) -> bool:
    return os.path.normcase(path) == os.path.normcase(str(project.resolve()))


def origin_of(storage: Path) -> dict[str, Any] | None:
    """What ``project.json`` records of a folder, ``None`` if it cannot be read."""
    try:
        origin = json.loads((storage / ORIGIN).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return origin if isinstance(origin, dict) and "path" in origin else None


def _folders(root: Path) -> list[Path]:
    projects = root / PROJECTS
    if not projects.is_dir():
        return []
    return sorted(
        folder
        for folder in projects.iterdir()
        if folder.is_dir() and folder.name != UNTITLED
    )


def storage_folder(root: Path, project: Path | None) -> Path:
    """The folder of the data of a project file (of an untitled one: ``None``).

    The folder recording the file, else a new one named after it.

    Args:
        root: The user data directory of the application.
        project: The project file.
    """
    if project is None:
        return root / PROJECTS / UNTITLED
    for folder in _folders(root):
        origin = origin_of(folder)
        if origin is not None and _same_file(str(origin["path"]), project):
            return folder
    resolved = os.path.normcase(str(project.resolve()))
    key = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", project.name.split(".")[0]).strip("_")
    name = f"{stem or 'project'}-{key}"
    folder, count = root / PROJECTS / name, 2
    while origin_of(folder) is not None:  # Kept by a file moved from here.
        folder, count = root / PROJECTS / f"{name}-{count}", count + 1
    return folder


def _write_origin(storage: Path, origin: dict[str, Any]) -> None:
    storage.mkdir(parents=True, exist_ok=True)
    text = json.dumps(origin, indent=2, ensure_ascii=False) + "\n"
    write_text_atomically(storage / ORIGIN, text)


def mark(storage: Path, project: Path) -> None:
    """Create the folder of a project, or give it the new path of its file."""
    origin = origin_of(storage) or {}
    _write_origin(storage, {**origin, "path": str(project.resolve())})


def fingerprint(text: str) -> str:
    """The fingerprint of a script; line endings do not count."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def project_tree(project: Project) -> list[Any]:
    """The tree of the model of a project: names and kinds of its nodes."""

    def tree(node: Node) -> list[Any]:
        if isinstance(node, DriverNode):
            kind = f"driver:{node.kind}"
        elif isinstance(node, AssemblyNode):
            kind = "assembly"
        else:
            kind = f"component:{node.kind}"
        children = getattr(node, "children", [])
        return [node.name, kind, [tree(child) for child in children]]

    return tree(project.root)


def record(storage: Path, script: Path, project: Project) -> None:
    """Record what finds the folder again if the script is moved."""
    try:
        text = script.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    origin = origin_of(storage) or {"path": str(script.resolve())}
    origin.update(script=fingerprint(text), tree=project_tree(project))
    _write_origin(storage, origin)


def find_moved(
    root: Path, script: Path, project: Project
) -> tuple[Path | None, list[Path]]:
    """The folder of a script moved since it was saved or opened.

    Among the folders whose file no longer exists, the one recording the same
    fingerprint; else, the script having changed since, the one recording the
    same tree of the model, compared recursively.

    Returns:
        The folder, and the folders that matched as well when it is ambiguous
        (the folder is then ``None``).
    """
    try:
        text = script.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, []
    moved = []
    for folder in _folders(root):
        origin = origin_of(folder)
        if origin is None or _same_file(str(origin["path"]), script):
            continue
        if not Path(str(origin["path"])).exists():
            moved.append((folder, origin))
    tree = project_tree(project)
    for key, value in (("script", fingerprint(text)), ("tree", tree)):
        found = [folder for folder, origin in moved if origin.get(key) == value]
        if len(found) == 1:
            return found[0], []
        if found:
            return None, found
    return None, []


def prune(storage: Path) -> None:
    """Remove the folder of a project when it holds nothing but its origin."""
    if storage.is_dir() and all(
        path.name == ORIGIN or (path.is_dir() and not any(path.iterdir()))
        for path in storage.iterdir()
    ):
        shutil.rmtree(storage, ignore_errors=True)


def surrogate_files(model: Path) -> list[Path]:
    """The files of a surrogate: its model and its metadata."""
    return [model, model.with_suffix(".json")]


def move_into(source: Path, target: Path) -> dict[Path, Path]:
    """Move the entries of a folder into another one, then remove it if empty.

    Entries whose name is taken in ``target`` stay where they are.

    Returns:
        The new place of each entry moved.
    """
    moved: dict[Path, Path] = {}
    if not source.is_dir():
        return moved
    target.mkdir(parents=True, exist_ok=True)
    for entry in sorted(source.iterdir()):
        destination = target / entry.name
        if destination.exists():
            continue
        try:
            shutil.move(entry, destination)
        except OSError:  # In use (a run in progress): left where it is.
            continue
        moved[entry] = destination
    if not any(source.iterdir()):
        source.rmdir()
    return moved
