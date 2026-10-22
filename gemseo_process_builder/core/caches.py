"""The caches of the disciplines (SPEC § 8.7).

GEMSEO keeps the last execution of a discipline by default. A node may keep
none, every execution in memory, or every execution in an HDF5 file, where a
later run finds them. The setting lives in the ``config`` of a component or a
driver, and in the field ``cache`` of an assembly; it is absent for the default.

GEMSEO's cache knows the inputs, not the code: beside a cache file
(``<file>.gpb.json``), the application records a fingerprint of the node of
each HDF5 node when a run starts, and warns when the node changed since.
"""

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError

from gemseo_process_builder.core.atomic_write import write_text_atomically
from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Node
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.project_storage import CACHES

CacheType = Literal["none", "memory", "hdf5"]

RECORD_SUFFIX = ".gpb.json"


class CacheSetting(BaseModel):
    """What GEMSEO keeps of the executions of a discipline."""

    model_config = ConfigDict(extra="forbid")

    type: CacheType
    tolerance: float = Field(default=0.0, ge=0.0)
    """The inputs closer than this to cached ones are taken as equal."""

    file: str = ""
    """``hdf5``: the absolute path of the file."""

    node: str = ""
    """``hdf5``: the node of the file holding the entries (a path of names)."""


def cache_setting(node: Node) -> CacheSetting | None:
    """The cache of a node; ``None`` for GEMSEO's default or an invalid one."""
    data = node.cache if isinstance(node, AssemblyNode) else node.config.get("cache")
    if not data:
        return None
    try:
        return CacheSetting.model_validate(data)
    except ValidationError:
        return None


def cache_values(node: Node, setting: CacheSetting | None) -> dict[str, Any]:
    """The properties of ``setNodeProperties`` giving a node a cache setting."""
    data = setting.model_dump(exclude_defaults=True) if setting else None
    if isinstance(node, AssemblyNode):
        return {"cache": data or {}}
    config = {key: value for key, value in node.config.items() if key != "cache"}
    if data:
        config["cache"] = data
    return {"config": config}


WORKING_FOLDER_CACHES = "cache"
"""The folder of the file caches in the working folder of a study (SPEC § 8.7)."""


def default_file(
    storage: Path, project_name: str, working_folder: Path | None = None
) -> Path:
    """The default file of a cache (SPEC § 8.7).

    ``caches/<project name>.h5`` in the data of a project, or
    ``cache/<project name>.h5`` in the working folder of the study.
    """
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in project_name)
    folder = (
        storage / CACHES
        if working_folder is None
        else working_folder / WORKING_FOLDER_CACHES
    )
    return folder / f"{stem or 'project'}.h5"


def path_of_names(project: Project, node_id: str) -> str:
    """The names from the model down to a node, ``Study/Sizing``."""

    def walk(node: Node, names: list[str]) -> list[str] | None:
        if node.id == node_id:
            return names
        for child in getattr(node, "children", []):
            found = walk(child, [*names, child.name])
            if found is not None:
                return found
        return None

    found = walk(project.root, [])
    return "/".join(found) if found else ""


Cached = tuple[Node, list[Node], CacheSetting]


def cached_nodes(project: Project) -> Iterator[Cached]:
    """The nodes with a cache setting, with their ancestors (the model first)."""

    def walk(node: Node, ancestors: list[Node]) -> Iterator[Cached]:
        setting = cache_setting(node) if node is not project.root else None
        if setting is not None:
            yield node, ancestors, setting
        for child in getattr(node, "children", []):
            yield from walk(child, [*ancestors, node])

    yield from walk(project.root, [])


def builds_discipline(node: Node, ancestors: list[Node]) -> bool:
    """Whether the script builds a node as a discipline its cache is set on.

    Components; assemblies that are not transparent; drivers inside another
    node other than the model (wrapped in an adapter, ``is_nested``). Not the
    model, nor a driver run on its own (a scenario).

    Args:
        node: The node.
        ancestors: Its ancestors, the model first.
    """
    if not ancestors:
        return False
    if isinstance(node, ComponentNode):
        return True
    if isinstance(node, AssemblyNode):
        return not node.transparent
    return isinstance(node, DriverNode) and len(ancestors) > 1


def fingerprint(node: Node, folder: Path) -> str:
    """What identifies the code of a node, as a short hash.

    Its kind and configuration (its package version among them), the
    modification time of its module or descriptor; those of its children.

    Args:
        node: The node.
        folder: The folder relative paths are resolved against.
    """
    return hashlib.sha256(
        json.dumps(_identity(node, folder), sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def _identity(node: Node, folder: Path) -> dict[str, Any]:
    if isinstance(node, ComponentNode):
        config = {k: v for k, v in node.config.items() if k != "cache"}
        times = {}
        for key in ("module_path", "descriptor_path"):
            value = config.get(key)
            if isinstance(value, str) and value:
                path = Path(value) if Path(value).is_absolute() else folder / value
                times[key] = path.stat().st_mtime if path.is_file() else None
        return {"kind": node.kind, "config": config, "times": times}
    own = (
        {"mode": node.mode, "mda_settings": node.mda_settings}
        if isinstance(node, AssemblyNode)
        else {
            "kind": node.kind,
            "config": {k: v for k, v in node.config.items() if k != "cache"},
        }
    )
    return {
        **own,
        "children": {child.name: _identity(child, folder) for child in node.children},
    }


def record_path(file: Path) -> Path:
    """The fingerprints of the nodes of a cache file: ``<file>.gpb.json``."""
    return file.with_name(file.name + RECORD_SUFFIX)


def read_record(file: Path) -> dict[str, str]:
    """The fingerprint recorded for each node of a cache file."""
    path = record_path(file)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    nodes = data.get("nodes", {}) if isinstance(data, dict) else {}
    return {str(key): str(value) for key, value in nodes.items()}


def write_record(file: Path, changes: dict[str, str | None]) -> None:
    """Record fingerprints of nodes of a cache file (``None`` forgets a node)."""
    nodes = read_record(file)
    for key, value in changes.items():
        if value is None:
            nodes.pop(key, None)
        else:
            nodes[key] = value
    path = record_path(file)
    if not nodes:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomically(path, json.dumps({"nodes": nodes}, indent=2, sort_keys=True))


def record_fingerprints(
    project: Project, folder: Path, within: set[str] | None = None
) -> None:
    """Record the fingerprints of the nodes cached in files (when a run starts).

    Args:
        project: The project.
        folder: The folder relative paths are resolved against.
        within: The ids of the nodes to record (all by default).
    """
    by_file: dict[Path, dict[str, str | None]] = {}
    for node, _, setting in cached_nodes(project):
        if within is not None and node.id not in within:
            continue
        if setting.type == "hdf5" and setting.file and setting.node:
            by_file.setdefault(Path(setting.file), {})[setting.node] = fingerprint(
                node, folder
            )
    for file, changes in by_file.items():
        write_record(file, changes)
