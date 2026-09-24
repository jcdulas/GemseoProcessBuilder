"""Migrations of project files between schema versions.

Each migration turns the JSON data of version ``n`` into version ``n + 1``.
Opening an old file applies the migrations in memory; saving writes the current
version.
"""

from collections.abc import Callable
from typing import Any

from gemseo_process_builder.core.model import CURRENT_SCHEMA_VERSION

ProjectData = dict[str, Any]


class ProjectFileError(Exception):
    """A project file that cannot be read."""


def _from_0_to_1(data: ProjectData) -> ProjectData:
    """Version 0 stored node layouts directly under ``layout``."""
    layout = data.get("layout", {})
    if layout and "nodes" not in layout:
        data["layout"] = {"nodes": layout}
    return data


MIGRATIONS: dict[int, Callable[[ProjectData], ProjectData]] = {0: _from_0_to_1}
"""Migration from each version to the next one."""


def migrate(data: ProjectData) -> ProjectData:
    """Bring project data to the current schema version.

    Raises:
        ProjectFileError: When the file comes from a newer version of the
            application, or its version is invalid.
    """
    version = data.get("schema_version", 0)
    if not isinstance(version, int) or version < 0:
        msg = f"Invalid schema version: {version!r}."
        raise ProjectFileError(msg)
    if version > CURRENT_SCHEMA_VERSION:
        msg = (
            f"This project was saved by a newer version of GEMSEO Process Builder "
            f"(schema {version}, this version reads up to {CURRENT_SCHEMA_VERSION})."
        )
        raise ProjectFileError(msg)
    while version < CURRENT_SCHEMA_VERSION:
        data = MIGRATIONS[version](data)
        version += 1
        data["schema_version"] = version
    return data
