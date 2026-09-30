"""Algorithms and their settings: ``algorithms.*`` and ``settings.*`` methods.

The worker knows the installed algorithms; their lists and settings schemas
are cached until the worker restarts. The capabilities of the optimization
algorithms are loaded as soon as GEMSEO is ready, for the validation rules.
"""

import logging
from typing import Any

from pydantic import BaseModel
from PySide6.QtCore import QObject
from PySide6.QtCore import Signal

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.worker_client import WorkerClient
from gemseo_process_builder.app.worker_client import WorkerRequestError
from gemseo_process_builder.app.worker_client import WorkerUnavailableError
from gemseo_process_builder.app.worker_client import unwrap

_LOGGER = logging.getLogger(__name__)

TIMEOUT_S = 120.0


class KindParams(BaseModel):
    """Parameters of ``algorithms.list``."""

    kind: str


class SettingsParams(BaseModel):
    """Parameters of ``settings.schema`` and ``settings.validate``."""

    kind: str
    name: str
    settings: dict[str, Any] = {}


class AlgorithmService(QObject):
    """Cache what the worker says about algorithms."""

    capabilities_changed = Signal()

    def __init__(self, bridge: Bridge, worker: WorkerClient) -> None:
        super().__init__()
        self.bridge = bridge
        self.worker = worker
        self.lists: dict[str, list[dict[str, Any]]] = {}
        self.schemas: dict[tuple[str, str], dict[str, Any]] = {}
        worker.event_received.connect(self._worker_event)

    def capabilities(self) -> dict[str, dict[str, dict[str, bool]]]:
        """``{kind: {algorithm: capabilities}}`` for the lists loaded so far."""
        return {
            kind: {item["name"]: item["capabilities"] for item in items}
            for kind, items in self.lists.items()
        }

    def _worker_event(self, name: str, payload: Any) -> None:
        if name == "ready":  # A new worker: maybe another environment.
            self.lists.clear()
            self.schemas.clear()
        elif name == "gemseo_loaded":
            self.worker.request(
                "algorithms.list",
                {"kind": "optimization"},
                lambda response: self._preloaded("optimization", response),
                timeout=TIMEOUT_S,
            )

    def _preloaded(self, kind: str, response: dict[str, Any]) -> None:
        try:
            self.lists[kind] = unwrap(response)
        except (WorkerRequestError, WorkerUnavailableError) as error:
            _LOGGER.warning("The %s algorithms could not be listed: %s", kind, error)
            return
        self.capabilities_changed.emit()

    def _call(self, method: str, params: dict[str, Any]) -> Any:
        try:
            return self.worker.call(method, params, timeout=TIMEOUT_S)
        except WorkerRequestError as error:
            raise BridgeError(error.code, error.message) from None
        except WorkerUnavailableError as error:
            raise BridgeError(ErrorCode.WORKER_UNAVAILABLE, str(error)) from None

    def list_algorithms(self, params: KindParams) -> list[dict[str, Any]]:
        """The algorithms of a kind (``algorithms.list``)."""
        if params.kind not in self.lists:
            self.lists[params.kind] = self._call(
                "algorithms.list", {"kind": params.kind}
            )
            if params.kind == "optimization":
                self.capabilities_changed.emit()
        return self.lists[params.kind]

    def schema(self, params: SettingsParams) -> dict[str, Any]:
        """The JSON schema of an algorithm's settings (``settings.schema``)."""
        key = (params.kind, params.name)
        if key not in self.schemas:
            self.schemas[key] = self._call(
                "settings.schema", {"kind": params.kind, "name": params.name}
            )
        return self.schemas[key]

    def validate(self, params: SettingsParams) -> list[dict[str, str]]:
        """The errors of a set of settings (``settings.validate``)."""
        errors: list[dict[str, str]] = self._call(
            "settings.validate", params.model_dump()
        )
        return errors

    def register(self) -> None:
        """Register the ``algorithms.*`` and ``settings.*`` methods."""
        registry = self.bridge.registry
        registry.add("algorithms.list", self.list_algorithms, background=True)
        registry.add("settings.schema", self.schema, background=True)
        registry.add("settings.validate", self.validate, background=True)
