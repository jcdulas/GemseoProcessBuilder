"""Conversion of project file paths between absolute and project-relative forms.

In memory, projects use absolute paths. In files, paths are relative to the
project folder, so that a project folder can be moved or shared (SPEC § 4.2).
"""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

PATH_KEY_SUFFIX = "_path"
"""Configuration keys ending with this suffix hold file paths."""


def to_relative(path: str, folder: Path) -> str:
    """Express a path relative to a folder, with forward slashes.

    Paths on another drive (Windows) stay absolute.
    """
    if not path or not Path(path).is_absolute():
        return path
    try:
        relative = os.path.relpath(path, folder)
    except ValueError:
        return Path(path).as_posix()
    return Path(relative).as_posix()


def to_absolute(path: str, folder: Path) -> str:
    """Resolve a path relative to a folder; absolute paths are kept."""
    if not path or Path(path).is_absolute():
        return path
    return str((folder / path).resolve())


def convert_project_paths(
    data: dict[str, Any], convert: Callable[[str], str]
) -> dict[str, Any]:
    """Apply a conversion to every path of a project given as JSON data.

    Paths are: the catalog folders, the runs folder, surrogate and run folders,
    and every component or driver configuration value whose key ends with
    ``_path``.
    """
    settings = data.get("settings", {})
    settings["catalog_paths"] = [convert(p) for p in settings.get("catalog_paths", [])]
    if settings.get("runs_dir"):
        settings["runs_dir"] = convert(settings["runs_dir"])
    for surrogate in data.get("surrogates", []):
        surrogate["model_path"] = convert(surrogate["model_path"])
    for run in data.get("runs", []):
        run["run_path"] = convert(run["run_path"])
    if "root" in data:
        _convert_node_paths(data["root"], convert)
    return data


def _convert_node_paths(node: dict[str, Any], convert: Callable[[str], str]) -> None:
    config = node.get("config", {})
    for key, value in config.items():
        if key.endswith(PATH_KEY_SUFFIX) and isinstance(value, str):
            config[key] = convert(value)
    for child in node.get("children", []):
        _convert_node_paths(child, convert)
