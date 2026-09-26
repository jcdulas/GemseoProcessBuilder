"""What belongs to a project but is not its script (SPEC § 4.2.3).

Next to its script, the user only sees the script. The autosave, the lock,
the runs and the surrogates of a project live in a folder of the user data
directory of the application, one per project file:
``projects/<name>-<key>/``, the key made from the path of the file. The folder
holds ``project.json`` with that path, so that it can be traced back.
"""

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from gemseo_process_builder.core.atomic_write import write_text_atomically

PROJECTS = "projects"
UNTITLED = "untitled"
AUTOSAVE = "autosave.json"
LOCK = "lock"
RUNS = "runs"
SURROGATES = "surrogates"
ORIGIN = "project.json"


def storage_folder(root: Path, project: Path | None) -> Path:
    """The folder of the data of a project file (of an untitled one: ``None``).

    Args:
        root: The user data directory of the application.
        project: The project file.
    """
    if project is None:
        return root / PROJECTS / UNTITLED
    resolved = os.path.normcase(str(project.resolve()))
    key = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", project.name.split(".")[0]).strip("_")
    return root / PROJECTS / f"{stem or 'project'}-{key}"


def mark(storage: Path, project: Path) -> None:
    """Create the folder of a project, recording the path of its file."""
    storage.mkdir(parents=True, exist_ok=True)
    origin = json.dumps({"path": str(project.resolve())}, indent=2) + "\n"
    write_text_atomically(storage / ORIGIN, origin)


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
