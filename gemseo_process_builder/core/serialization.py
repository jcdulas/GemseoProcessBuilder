"""Reading and writing ``.gpb.json`` project files (SPEC § 4.2).

Files are indented JSON with sorted keys, so the same project always gives the
same bytes and diffs stay readable. Paths are stored relative to the project
folder.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from gemseo_process_builder.core.atomic_write import write_text_atomically
from gemseo_process_builder.core.migrations import ProjectFileError
from gemseo_process_builder.core.migrations import migrate
from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Node
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.paths import convert_project_paths
from gemseo_process_builder.core.paths import to_absolute
from gemseo_process_builder.core.paths import to_relative

PROJECT_SUFFIX = ".gpb.json"


def _write_node_types(node: Node, data: dict[str, Any]) -> None:
    """Write the ``type`` of each node, which has a default but is always needed."""
    data["type"] = node.type
    if isinstance(node, AssemblyNode | DriverNode):
        for child, child_data in zip(
            node.children, data.get("children", []), strict=True
        ):
            _write_node_types(child, child_data)


def project_to_data(project: Project, folder: Path) -> dict[str, Any]:
    """Return the JSON data of a project, with paths relative to ``folder``.

    Default values are left out to keep files short; the schema version, the
    metadata, the root node and the node types are always written.
    """
    data = project.model_dump(mode="json", exclude_defaults=True)
    data["schema_version"] = project.schema_version
    data["metadata"] = project.metadata.model_dump(mode="json")
    data["root"] = project.root.model_dump(mode="json", exclude_defaults=True)
    _write_node_types(project.root, data["root"])
    return convert_project_paths(data, lambda path: to_relative(path, folder))


def dumps(project: Project, folder: Path) -> str:
    """Return the file content of a project saved in ``folder``."""
    text = json.dumps(
        project_to_data(project, folder), indent=2, sort_keys=True, ensure_ascii=False
    )
    return text + "\n"


def loads(text: str, folder: Path) -> Project:
    """Read a project from file content, resolving paths against ``folder``.

    Raises:
        ProjectFileError: When the content is not a valid project.
    """
    try:
        data = json.loads(text)
    except ValueError as error:
        msg = f"The file is not valid JSON: {error}"
        raise ProjectFileError(msg) from None
    if not isinstance(data, dict):
        msg = "The file does not contain a project."
        raise ProjectFileError(msg)
    data = migrate(data)
    data = convert_project_paths(data, lambda path: to_absolute(path, folder))
    try:
        return Project.model_validate(data)
    except ValidationError as error:
        msg = f"The project is invalid:\n{error}"
        raise ProjectFileError(msg) from None


def load_project(path: Path) -> Project:
    """Read a project file.

    Raises:
        ProjectFileError: When the file cannot be read or is not a valid project.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        msg = f"Cannot read {path}: {error.strerror}"
        raise ProjectFileError(msg) from None
    return loads(text, path.parent)


def save_project(project: Project, path: Path) -> None:
    """Write a project file."""
    write_text_atomically(path, dumps(project, path.parent))


def project_name_from_path(path: Path) -> str:
    """Return the project name given by a file name like ``Sellar.gpb.json``."""
    name = path.name
    return name[: -len(PROJECT_SUFFIX)] if name.endswith(PROJECT_SUFFIX) else path.stem
