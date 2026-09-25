"""Application actions shared by the native menus, the toolbar and shortcuts.

Actions are defined once, here. The page receives them with ``actions.list``,
attaches the behavior of each one, and handles the keyboard shortcuts itself
(the web view has the focus). The page shows them in the application menu of its
top bar. The native menu bar is built too but hidden: its actions run the few
actions handled natively (like Quit), through ``actions.triggerNative``.
"""

from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow
from PySide6.QtWidgets import QMenu

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode


@dataclass(frozen=True)
class ActionDefinition:
    """An action of the application."""

    id: str
    menu: str
    label: str
    shortcuts: tuple[str, ...] = ()
    """Shortcuts like ``"Ctrl+Shift+S"``; the first one is shown in the menu."""

    native: bool = False
    """Whether the action is handled by Python instead of the page."""

    separator_before: bool = False


MENUS = ("File", "Edit", "View", "Model", "Run", "Tools", "Help")

ACTIONS = (
    ActionDefinition("file.new", "File", "New project", ("Ctrl+N",)),
    ActionDefinition("file.open", "File", "Open project…", ("Ctrl+O",)),
    ActionDefinition("file.save", "File", "Save", ("Ctrl+S",), separator_before=True),
    ActionDefinition("file.saveAs", "File", "Save as…", ("Ctrl+Shift+S",)),
    ActionDefinition(
        "file.exportPython", "File", "Export Python script…", separator_before=True
    ),
    ActionDefinition("file.exportImage", "File", "Export image…"),
    ActionDefinition("file.exportReport", "File", "Export report…"),
    ActionDefinition("file.close", "File", "Close project", separator_before=True),
    ActionDefinition("file.quit", "File", "Quit", native=True, separator_before=True),
    ActionDefinition("edit.undo", "Edit", "Undo", ("Ctrl+Z",)),
    ActionDefinition("edit.redo", "Edit", "Redo", ("Ctrl+Y", "Ctrl+Shift+Z")),
    ActionDefinition("edit.cut", "Edit", "Cut", ("Ctrl+X",), separator_before=True),
    ActionDefinition("edit.copy", "Edit", "Copy", ("Ctrl+C",)),
    ActionDefinition("edit.paste", "Edit", "Paste", ("Ctrl+V",)),
    ActionDefinition("edit.duplicate", "Edit", "Duplicate", ("Ctrl+D",)),
    ActionDefinition("edit.delete", "Edit", "Delete", ("Delete",)),
    ActionDefinition("edit.rename", "Edit", "Rename", ("F2",)),
    ActionDefinition(
        "edit.selectAll", "Edit", "Select all", ("Ctrl+A",), separator_before=True
    ),
    ActionDefinition("edit.find", "Edit", "Find…", ("Ctrl+F",)),
    ActionDefinition("view.toggleLeft", "View", "Show left panel"),
    ActionDefinition("view.toggleRight", "View", "Show inspector"),
    ActionDefinition("view.toggleBottom", "View", "Show bottom panel"),
    ActionDefinition("view.fit", "View", "Fit to view", ("F",), separator_before=True),
    ActionDefinition("view.autoLayout", "View", "Auto-layout", ("Ctrl+L",)),
    ActionDefinition(
        "view.up", "View", "Go up one level", ("Alt+ArrowUp", "Backspace")
    ),
    ActionDefinition("view.n2", "View", "N2 matrix", separator_before=True),
    ActionDefinition("view.xdsm", "View", "XDSM"),
    ActionDefinition("model.validate", "Model", "Validate", ("F7",)),
    ActionDefinition(
        "model.group",
        "Model",
        "Group into assembly",
        ("Ctrl+G",),
        separator_before=True,
    ),
    ActionDefinition("model.ungroup", "Model", "Ungroup", ("Ctrl+Shift+G",)),
    ActionDefinition(
        "model.projectSettings", "Model", "Project settings…", separator_before=True
    ),
    ActionDefinition("run.start", "Run", "Run", ("F5",)),
    ActionDefinition("run.stop", "Run", "Stop", ("Shift+F5",)),
    ActionDefinition("tools.newWrapper", "Tools", "New executable wrapper…"),
    ActionDefinition(
        "tools.preferences", "Tools", "Preferences…", separator_before=True
    ),
    ActionDefinition("tools.restartWorker", "Tools", "Restart worker"),
    ActionDefinition("help.shortcuts", "Help", "Keyboard shortcuts"),
    ActionDefinition("help.about", "Help", "About GEMSEO Process Builder"),
)


class ActionStatesParams(BaseModel):
    """Parameters of ``actions.setState``."""

    enabled: dict[str, bool] = {}
    checked: dict[str, bool] = {}


class TriggerParams(BaseModel):
    """Parameters of ``actions.triggerNative``."""

    id: str


class NativeMenus:
    """The native menu bar, built from ``ACTIONS``, hidden behind the page's menu."""

    def __init__(self, window: QMainWindow, bridge: Bridge) -> None:
        self._bridge = bridge
        window.menuBar().setVisible(False)
        self.menus: dict[str, QMenu] = {
            name: window.menuBar().addMenu(f"&{name}") for name in MENUS
        }
        self.actions: dict[str, QAction] = {}
        for definition in ACTIONS:
            self._add(definition)
        self.actions["file.quit"].triggered.connect(window.close)
        self.recent_menu = QMenu("Open recent", window)
        self.menus["File"].insertMenu(self.actions["file.save"], self.recent_menu)
        self.menus["File"].insertSeparator(self.actions["file.save"])

    def set_recent_projects(
        self, paths: list[str], open_project: Callable[[str], None]
    ) -> None:
        """Fill the Open recent submenu."""
        self.recent_menu.clear()
        for path in paths:
            action = self.recent_menu.addAction(path)
            action.triggered.connect(lambda _=False, p=path: open_project(p))
        self.recent_menu.setEnabled(bool(paths))

    def _add(self, definition: ActionDefinition) -> None:
        menu = self.menus[definition.menu]
        if definition.separator_before:
            menu.addSeparator()
        text = definition.label
        if definition.shortcuts:
            # Shown only: the page handles the keys itself.
            text += "\t" + definition.shortcuts[0].replace("Arrow", "")
        action = menu.addAction(text)
        if definition.id.startswith("view.toggle"):
            action.setCheckable(True)
            action.setChecked(True)
        if not definition.native:
            action.setEnabled(False)
            action.triggered.connect(
                lambda: self._bridge.emit_event("action.invoke", {"id": definition.id})
            )
        self.actions[definition.id] = action

    def set_states(self, params: ActionStatesParams) -> None:
        """Enable, disable, check or uncheck actions."""
        for action_id, enabled in params.enabled.items():
            if action_id in self.actions:
                self.actions[action_id].setEnabled(enabled)
        for action_id, checked in params.checked.items():
            if action_id in self.actions:
                self.actions[action_id].setChecked(checked)

    def trigger(self, params: TriggerParams) -> None:
        """Run a native action, once the bridge call has returned.

        Raises:
            BridgeError: If the action is not a native one.
        """
        definition = next((item for item in ACTIONS if item.id == params.id), None)
        if definition is None or not definition.native:
            raise BridgeError(
                ErrorCode.INVALID_PARAMS, f"No native action {params.id}."
            )
        # Quitting may ask about unsaved changes: not inside the bridge call.
        QTimer.singleShot(0, self.actions[params.id].trigger)


def list_actions() -> list[dict[str, Any]]:
    """Return the action definitions for the page."""
    return [asdict(definition) for definition in ACTIONS]


def register_action_methods(bridge: Bridge, menus: NativeMenus) -> None:
    """Register ``actions.list``, ``actions.setState`` and ``actions.triggerNative``."""
    bridge.registry.add("actions.list", list_actions)
    bridge.registry.add("actions.setState", menus.set_states)
    bridge.registry.add("actions.triggerNative", menus.trigger)
