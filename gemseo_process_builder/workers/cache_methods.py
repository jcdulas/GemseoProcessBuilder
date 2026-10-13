"""The HDF5 cache files of the disciplines (SPEC § 8.7; runs in the worker).

GEMSEO's ``HDF5Cache`` keeps the executions of a discipline under a node of
its file: one group per entry (``1``, ``2``…), with the hash of its inputs and
its input and output data.
"""

from pathlib import Path
from typing import Any

from gemseo_process_builder.workers.server import WorkerError


def entries(file: Path, node: str) -> int | None:
    """The entries of a node of a cache file; ``None`` without the file or node."""
    import h5py

    if not file.is_file():
        return None
    with h5py.File(file, "r") as hdf:
        group = hdf.get(node)
        if not isinstance(group, h5py.Group):
            return None
        return sum(1 for item in group.values() if isinstance(item, h5py.Group))


def clear(file: Path, node: str) -> int:
    """Remove a node of a cache file; the entries it held."""
    import h5py

    count = entries(file, node) or 0
    if count or (file.is_file() and _has(file, node)):
        try:
            with h5py.File(file, "a") as hdf:
                del hdf[node]
        except OSError as error:  # A run holds the file.
            msg = f"The cache file {file.name} is in use: {error}"
            raise WorkerError("busy", msg) from None
    return count


def _has(file: Path, node: str) -> bool:
    import h5py

    with h5py.File(file, "r") as hdf:
        return node in hdf


def _target(params: dict[str, Any]) -> tuple[Path, str]:
    file, node = params.get("file"), params.get("node")
    if not file or not node:
        msg = "A cache file and a node are needed."
        raise WorkerError("invalid_params", msg)
    return Path(str(file)), str(node)


def _inspect(params: dict[str, Any], context: Any) -> dict[str, Any]:
    """Worker method ``cache.inspect``: the entries of a node of a cache file."""
    file, node = _target(params)
    try:
        count = entries(file, node)
    except OSError as error:
        msg = f"The cache file {file.name} cannot be read: {error}"
        raise WorkerError("busy", msg) from None
    return {"exists": count is not None, "entries": count or 0}


def _clear(params: dict[str, Any], context: Any) -> dict[str, Any]:
    """Worker method ``cache.clear``: remove a node of a cache file."""
    file, node = _target(params)
    return {"removed": clear(file, node)}


def register(server: Any) -> None:
    """Add the cache methods to the worker."""
    server.add("cache.inspect", _inspect)
    server.add("cache.clear", _clear)
