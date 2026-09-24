"""Automatic introspection of components (SPEC § 7.1 to § 7.3).

When a component is added, or its configuration changes, the worker computes
its ports; they are merged with the current ones (keeping units, descriptions
and global names) and applied without an undo entry: ports always follow the
configuration, so undoing the configuration change introspects again.
"""

import hashlib
import json
import logging
from typing import Any

from pydantic import BaseModel
from PySide6.QtCore import QObject
from PySide6.QtCore import QTimer

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.app.worker_client import WorkerClient
from gemseo_process_builder.app.worker_client import WorkerRequestError
from gemseo_process_builder.app.worker_client import WorkerUnavailableError
from gemseo_process_builder.app.worker_client import unwrap
from gemseo_process_builder.core.commands import CommandError
from gemseo_process_builder.core.commands import SetPorts
from gemseo_process_builder.core.document import Change
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.ports import merge_ports

_LOGGER = logging.getLogger(__name__)

INTROSPECTED_KINDS = {"analytic", "python_function", "python_class"}
DEBOUNCE_MS = 400
INTROSPECTION_TIMEOUT_S = 120.0


def config_hash(node: ComponentNode) -> str:
    """A fingerprint of what determines the ports of a component."""
    text = json.dumps({"kind": node.kind, "config": node.config}, sort_keys=True)
    return hashlib.sha1(text.encode()).hexdigest()


class IdParams(BaseModel):
    """Parameters holding a node id."""

    id: str


class ConfigParams(BaseModel):
    """Parameters holding a component configuration."""

    config: dict[str, Any]


class ComponentService(QObject):
    """Introspect components when needed and report their status."""

    def __init__(
        self, session: ProjectSession, bridge: Bridge, worker: WorkerClient
    ) -> None:
        super().__init__()
        self.session = session
        self.bridge = bridge
        self.worker = worker
        self.known: dict[str, str] = {}
        """Configuration fingerprint of each component when its ports were computed."""

        self.states: dict[str, dict[str, Any]] = {}
        self._queued: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._introspect_queued)
        session.document.on_change(self._document_changed)
        session.on_change(self._project_may_be_new)
        self._project = session.project
        self._remember_all()

    # Detection -----------------------------------------------------------------

    def _remember_all(self) -> None:
        """Consider the ports of a freshly opened project as up to date."""
        self.known.clear()
        self.states.clear()
        for node, _ in iter_nodes(self.session.project.root):
            if isinstance(node, ComponentNode) and node.kind in INTROSPECTED_KINDS:
                if node.ports:
                    self.known[node.id] = config_hash(node)
                else:
                    self._queued.add(node.id)
        if self._queued:
            self._timer.start()

    def _project_may_be_new(self) -> None:
        if self.session.project is not self._project:
            self._project = self.session.project
            self._remember_all()

    def _document_changed(self, changes: list[Change], rev: int) -> None:
        for change in changes:
            if change["kind"] != "node" or change["op"] != "upsert":
                continue
            data = change["data"]
            if (
                data.get("type") != "component"
                or data.get("kind") not in INTROSPECTED_KINDS
            ):
                continue
            node = self.session.project.find(change["id"])
            if isinstance(node, ComponentNode) and self.known.get(
                node.id
            ) != config_hash(node):
                self._queued.add(node.id)
        if self._queued:
            self._timer.start()

    # Introspection -------------------------------------------------------------

    def _introspect_queued(self) -> None:
        queued, self._queued = self._queued, set()
        for node_id in queued:
            self.introspect(node_id)

    def introspect(self, node_id: str) -> None:
        """Ask the worker for the ports of a component."""
        node = self.session.project.find(node_id)
        if not isinstance(node, ComponentNode) or node.kind not in INTROSPECTED_KINDS:
            return
        fingerprint = config_hash(node)
        self.known[node_id] = fingerprint
        self._set_state(node_id, "running")
        self.worker.request(
            "component.introspect",
            {"kind": node.kind, "config": node.config},
            lambda response: self._received(node_id, fingerprint, response),
            timeout=INTROSPECTION_TIMEOUT_S,
        )

    def _received(
        self, node_id: str, fingerprint: str, response: dict[str, Any]
    ) -> None:
        node = self.session.project.find(node_id)
        if not isinstance(node, ComponentNode) or config_hash(node) != fingerprint:
            return  # Deleted or changed meanwhile: a newer request is on its way.
        try:
            introspected = unwrap(response)
        except (WorkerRequestError, WorkerUnavailableError) as error:
            self._set_state(node_id, "error", str(error))
            return
        linked = {
            (link.source.port, "out")
            for link in self.session.project.links
            if link.source.node == node_id
        } | {
            (link.target.port, "in")
            for link in self.session.project.links
            if link.target.node == node_id
        }
        ports = merge_ports(node.ports, introspected, linked)
        try:
            self.session.document.execute(
                SetPorts(id=node_id, ports=ports), undoable=False, content=True
            )
        except CommandError as error:
            self._set_state(node_id, "error", str(error))
            return
        self._set_state(node_id, "done")

    def _set_state(self, node_id: str, state: str, error: str = "") -> None:
        self.states[node_id] = {"state": state, "error": error}
        self.bridge.emit_event(
            "component.status", {"id": node_id, "state": state, "error": error}
        )

    # Bridge --------------------------------------------------------------------

    def register(self) -> None:
        """Register ``component.*`` methods."""

        def introspect(params: IdParams) -> dict[str, Any]:
            self.introspect(params.id)
            return self.states.get(params.id, {"state": "idle", "error": ""})

        def states() -> dict[str, Any]:
            return self.states

        def init_signature(params: ConfigParams) -> Any:
            try:
                return self.worker.call(
                    "component.init_signature", {"config": params.config}, timeout=60
                )
            except WorkerRequestError as error:
                raise BridgeError(error.code, error.message) from None
            except WorkerUnavailableError as error:
                raise BridgeError(ErrorCode.WORKER_UNAVAILABLE, str(error)) from None

        registry = self.bridge.registry
        registry.add("component.introspect", introspect)
        registry.add("component.states", states)
        registry.add("component.initSignature", init_signature, background=True)
