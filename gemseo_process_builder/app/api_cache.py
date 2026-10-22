"""The caches of the disciplines for the inspector: ``cache.*`` methods (SPEC § 8.7).

The entries of a file cache are counted, and removed, by the worker (``h5py``);
the fingerprints recorded beside the file are compared here with the node now.
"""

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.app.worker_client import WorkerClient
from gemseo_process_builder.app.worker_client import WorkerRequestError
from gemseo_process_builder.app.worker_client import WorkerUnavailableError
from gemseo_process_builder.core.caches import CacheSetting
from gemseo_process_builder.core.caches import cache_setting
from gemseo_process_builder.core.caches import default_file
from gemseo_process_builder.core.caches import fingerprint
from gemseo_process_builder.core.caches import read_record
from gemseo_process_builder.core.caches import write_record
from gemseo_process_builder.core.drivers import nearest_working_folder
from gemseo_process_builder.core.model import Node

TIMEOUT_S = 30.0


class CacheParams(BaseModel):
    """Parameters of ``cache.inspect``, ``cache.clear`` and ``cache.keep``."""

    id: str


class DefaultFileParams(BaseModel):
    """Parameters of ``cache.defaultFile``: the node whose cache gets the file."""

    id: str = ""


class CacheService:
    """The file caches of the nodes of the project."""

    def __init__(
        self, session: ProjectSession, bridge: Bridge, worker: WorkerClient
    ) -> None:
        self.session = session
        self.bridge = bridge
        self.worker = worker

    def _file_cache(self, node_id: str) -> tuple[Node, CacheSetting]:
        node = self.session.project.find(node_id)
        setting = cache_setting(node) if node is not None else None
        if node is None or setting is None or setting.type != "hdf5":
            msg = "This node has no file cache."
            raise BridgeError(ErrorCode.NOT_FOUND, msg)
        if not setting.file or not setting.node:
            msg = "Choose the file and the node of the cache first."
            raise BridgeError(ErrorCode.INVALID_PARAMS, msg)
        return node, setting

    def _call(self, method: str, setting: CacheSetting) -> Any:
        try:
            return self.worker.call(
                method, {"file": setting.file, "node": setting.node}, timeout=TIMEOUT_S
            )
        except WorkerUnavailableError as error:
            raise BridgeError(ErrorCode.WORKER_UNAVAILABLE, str(error)) from None
        except WorkerRequestError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None

    def default_file(self, params: DefaultFileParams) -> dict[str, str]:
        """The default file of the cache of a node (SPEC § 8.7).

        ``cache/`` of the working folder of its study, else ``caches/`` in the
        data of the project.
        """
        folder = (
            nearest_working_folder(self.session.project, params.id, self.session.folder)
            if params.id
            else None
        )
        file = default_file(self.session.storage, self.session.name, folder)
        return {"file": str(file)}

    def inspect(self, params: CacheParams) -> dict[str, Any]:
        """The entries of the node of a file cache, and whether they are current.

        ``differs``: the node holds entries recorded for another version of the
        component (its fingerprint changed since).
        """
        node, setting = self._file_cache(params.id)
        found = self._call("cache.inspect", setting)
        recorded = read_record(Path(setting.file)).get(setting.node)
        current = fingerprint(node, self.session.folder)
        return {
            "exists": bool(found["exists"]),
            "entries": int(found["entries"]),
            "recorded": recorded is not None,
            "differs": bool(found["entries"]) and recorded not in (None, current),
        }

    def clear(self, params: CacheParams) -> dict[str, Any]:
        """Remove the node of a file cache and its fingerprint."""
        _, setting = self._file_cache(params.id)
        removed = self._call("cache.clear", setting)
        write_record(Path(setting.file), {setting.node: None})
        return {"removed": int(removed["removed"])}

    def keep(self, params: CacheParams) -> dict[str, Any]:
        """Keep the entries of a node: record the fingerprint of the node now."""
        node, setting = self._file_cache(params.id)
        current = fingerprint(node, self.session.folder)
        write_record(Path(setting.file), {setting.node: current})
        return {"kept": True}

    def register(self) -> None:
        """Register the ``cache.*`` methods."""
        registry = self.bridge.registry
        registry.add("cache.defaultFile", self.default_file)
        registry.add("cache.inspect", self.inspect, background=True)
        registry.add("cache.clear", self.clear, background=True)
        registry.add("cache.keep", self.keep)
