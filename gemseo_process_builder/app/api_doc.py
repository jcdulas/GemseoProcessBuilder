"""Document editing methods: ``doc.*``.

The page edits the project by sending commands; every change comes back as a
``document.patch`` event, and the undo state as an ``undo.state`` event.
"""

import json
from typing import Any
from typing import Protocol

from pydantic import BaseModel
from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QApplication

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.core.clipboard import CLIPBOARD_MIME_TYPE
from gemseo_process_builder.core.clipboard import extract_subgraph
from gemseo_process_builder.core.clipboard import paste_command
from gemseo_process_builder.core.commands import CommandError
from gemseo_process_builder.core.commands import DeleteNodes
from gemseo_process_builder.core.commands import parse_command
from gemseo_process_builder.core.document import Change


class Clipboard(Protocol):
    """Where copied sub-graphs go."""

    def put(self, data: dict[str, Any]) -> None:
        """Store a copied sub-graph."""

    def get(self) -> dict[str, Any] | None:
        """Return the stored sub-graph, if any."""


class QtClipboard:
    """The system clipboard, with a custom MIME type and a JSON text fallback."""

    def put(self, data: dict[str, Any]) -> None:
        """Store a copied sub-graph."""
        text = json.dumps(data)
        mime = QMimeData()
        mime.setData(CLIPBOARD_MIME_TYPE, text.encode())
        mime.setText(text)
        QApplication.clipboard().setMimeData(mime)

    def get(self) -> dict[str, Any] | None:
        """Return the stored sub-graph, if any."""
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return None
        if mime.hasFormat(CLIPBOARD_MIME_TYPE):
            text = bytes(mime.data(CLIPBOARD_MIME_TYPE).data()).decode()
        elif mime.hasText():
            text = mime.text()
        else:
            return None
        try:
            data = json.loads(text)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None


class ExecuteParams(BaseModel):
    """Parameters of ``doc.execute``."""

    command: dict[str, Any]
    undoable: bool = True


class ExecuteManyParams(BaseModel):
    """Parameters of ``doc.executeMany``: one undo step for several commands."""

    commands: list[dict[str, Any]]
    label: str


class IdsParams(BaseModel):
    """Parameters holding node ids."""

    ids: list[str]


class PasteParams(BaseModel):
    """Parameters of ``doc.paste``."""

    parent: str
    x: float | None = None
    y: float | None = None


class DocController:
    """Edit the document of the session from the page."""

    def __init__(
        self, session: ProjectSession, bridge: Bridge, clipboard: Clipboard
    ) -> None:
        self.session = session
        self.bridge = bridge
        self.clipboard = clipboard
        session.document.on_change(self._changed)

    def _changed(self, changes: list[Change], rev: int) -> None:
        self.bridge.emit_event("document.patch", {"rev": rev, "changes": changes})
        self.bridge.emit_event("undo.state", self.session.document.undo_state())

    def _run(self, action: Any) -> dict[str, Any]:
        try:
            rev = action()
        except CommandError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        return {"rev": rev}

    def snapshot(self) -> dict[str, Any]:
        """The whole document in flat form (``doc.snapshot``)."""
        return self.session.document.snapshot()

    def execute(self, params: ExecuteParams) -> dict[str, Any]:
        """Apply one command (``doc.execute``)."""
        document = self.session.document
        return self._run(
            lambda: document.execute(
                parse_command(params.command), undoable=params.undoable
            )
        )

    def execute_many(self, params: ExecuteManyParams) -> dict[str, Any]:
        """Apply several commands as one undo step (``doc.executeMany``)."""
        document = self.session.document
        return self._run(
            lambda: document.execute_many(
                [parse_command(command) for command in params.commands], params.label
            )
        )

    def undo(self) -> dict[str, Any]:
        """Undo the last step (``doc.undo``)."""
        return self._run(self.session.document.undo)

    def redo(self) -> dict[str, Any]:
        """Redo the last undone step (``doc.redo``)."""
        return self._run(self.session.document.redo)

    def undo_state(self) -> dict[str, Any]:
        """Whether undo and redo are possible (``doc.undoState``)."""
        return self.session.document.undo_state()

    def copy(self, params: IdsParams) -> dict[str, Any]:
        """Copy nodes to the clipboard (``doc.copy``)."""
        data = extract_subgraph(self.session.project, params.ids)
        self.clipboard.put(data)
        return {"count": len(data["nodes"])}

    def cut(self, params: IdsParams) -> dict[str, Any]:
        """Copy nodes to the clipboard, then delete them (``doc.cut``)."""
        self.copy(params)
        return self._run(
            lambda: self.session.document.execute(DeleteNodes(ids=params.ids))
        )

    def paste(self, params: PasteParams) -> dict[str, Any]:
        """Paste the clipboard into a container (``doc.paste``)."""
        data = self.clipboard.get()
        if data is None:
            raise BridgeError(
                ErrorCode.CONFLICT, "The clipboard does not contain nodes."
            )
        position = (
            (params.x, params.y)
            if params.x is not None and params.y is not None
            else None
        )
        return self._paste(data, params.parent, position)

    def duplicate(self, params: IdsParams) -> dict[str, Any]:
        """Paste a copy of nodes next to them (``doc.duplicate``)."""
        project = self.session.project
        if not params.ids:
            return {"rev": self.session.document.rev, "ids": []}
        parent = project.parent_of(params.ids[0])
        if parent is None:
            raise BridgeError(
                ErrorCode.CONFLICT, "The model itself cannot be duplicated."
            )
        return self._paste(extract_subgraph(project, params.ids), parent.id, None)

    def _paste(
        self, data: dict[str, Any], parent: str, position: tuple[float, float] | None
    ) -> dict[str, Any]:
        document = self.session.document
        try:
            command = paste_command(document.project, data, parent, position)
            rev = document.execute(command)
        except CommandError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        return {"rev": rev, "ids": [item.node["id"] for item in command.items]}

    def register(self) -> None:
        """Register the ``doc.*`` methods."""
        registry = self.bridge.registry
        registry.add("doc.snapshot", self.snapshot)
        registry.add("doc.execute", self.execute)
        registry.add("doc.executeMany", self.execute_many)
        registry.add("doc.undo", self.undo)
        registry.add("doc.redo", self.redo)
        registry.add("doc.undoState", self.undo_state)
        registry.add("doc.copy", self.copy)
        registry.add("doc.cut", self.cut)
        registry.add("doc.paste", self.paste)
        registry.add("doc.duplicate", self.duplicate)
