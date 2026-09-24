"""Application actions shared by the native menus, the toolbar and shortcuts.

Actions are defined once, here. The page receives them with ``actions.list``,
attaches the behavior of each one, and handles the keyboard shortcuts itself
(the web view has the focus). Native menus only show the shortcut text; clicking
a menu item sends an ``action.invoke`` event to the page, except for the few
actions handled natively (like Quit).
"""

from dataclasses import asdict
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow
from PySide6.QtWidgets import QMenu

from gemseo_process_builder.app.bridge import Bridge


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
    ActionDefinition("file.close", "File", "Close project"),
    ActionDefinition("file.quit", "File", "Quit", native=True, separator_before=True),
    ActionDefinition("edit.undo", "Edit", "Undo", ("Ctrl+Z",)),
    ActionDefinition("edit.redo", "Edit", "Redo", ("Ctrl+Y", "Ctrl+Shift+Z")),
    ActionDefinition("edit.cut", "Edit", "Cut", ("Ctrl+X",), separator_before=True),
    ActionDefinition("edit.copy", "Edit", "Copy", ("Ctrl+C",)),
    ActionDefinition("edit.paste", "Edit", "Paste", ("Ctrl+V",)),
    ActionDefinition("edit.duplicate", "Edit", "Duplicate", ("Ctrl+D",)),
    ActionDefinition("edit.delete", "Edit", "Delete", ("Delete",)),
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
    ActionDefinition("tools.preferences", "Tools", "Preferences…"),
    ActionDefinition("tools.restartWorker", "Tools", "Restart worker"),
    ActionDefinition("help.shortcuts", "Help", "Keyboard shortcuts"),
    ActionDefinition("help.about", "Help", "About GEMSEO Process Builder"),
)


class ActionStatesParams(BaseModel):
    """Parameters of ``actions.setState``."""

    enabled: dict[str, bool] = {}
    checked: dict[str, bool] = {}


class NativeMenus:
    """The native menu bar, built from ``ACTIONS``."""

    def __init__(self, window: QMainWindow, bridge: Bridge) -> None:
        self._bridge = bridge
        self.menus: dict[str, QMenu] = {
            name: window.menuBar().addMenu(f"&{name}") for name in MENUS
        }
        self.actions: dict[str, QAction] = {}
        for definition in ACTIONS:
            self._add(definition)
        self.actions["file.quit"].triggered.connect(window.close)

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


def list_actions() -> list[dict[str, Any]]:
    """Return the action definitions for the page."""
    return [asdict(definition) for definition in ACTIONS]


def register_action_methods(bridge: Bridge, menus: NativeMenus) -> None:
    """Register ``actions.list`` and ``actions.setState``."""
    bridge.registry.add("actions.list", list_actions)
    bridge.registry.add("actions.setState", menus.set_states)
