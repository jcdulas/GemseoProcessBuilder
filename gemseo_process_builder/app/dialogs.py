"""Native dialogs, behind an interface that tests can replace."""

from pathlib import Path
from typing import Literal
from typing import Protocol

from pydantic import BaseModel
from PySide6.QtWidgets import QFileDialog
from PySide6.QtWidgets import QMessageBox
from PySide6.QtWidgets import QWidget

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.core.serialization import PROJECT_SUFFIX

PROJECT_FILTER = f"GEMSEO Process Builder projects (*{PROJECT_SUFFIX})"

UnsavedChoice = Literal["save", "discard", "cancel"]


class Dialogs(Protocol):
    """The questions the application asks the user."""

    def ask_open_project(self) -> Path | None:
        """Ask for a project file to open; ``None`` if cancelled."""

    def ask_save_project(self, suggested_name: str) -> Path | None:
        """Ask where to save the project; ``None`` if cancelled."""

    def ask_unsaved_changes(self, project_name: str) -> UnsavedChoice:
        """Ask what to do with unsaved changes."""

    def ask_recover(self, project_name: str) -> bool:
        """Ask whether to recover an autosave newer than the project."""

    def show_error(self, title: str, message: str) -> None:
        """Show an error."""


class QtDialogs:
    """Dialogs shown with Qt widgets."""

    def __init__(self, parent: QWidget | None = None) -> None:
        self.parent = parent

    def ask_open_project(self) -> Path | None:
        """Ask for a project file to open; ``None`` if cancelled."""
        path, _ = QFileDialog.getOpenFileName(
            self.parent, "Open project", "", PROJECT_FILTER
        )
        return Path(path) if path else None

    def ask_save_project(self, suggested_name: str) -> Path | None:
        """Ask where to save the project; ``None`` if cancelled."""
        path, _ = QFileDialog.getSaveFileName(
            self.parent, "Save project", suggested_name + PROJECT_SUFFIX, PROJECT_FILTER
        )
        if not path:
            return None
        if not path.endswith(PROJECT_SUFFIX):
            path += PROJECT_SUFFIX
        return Path(path)

    def ask_unsaved_changes(self, project_name: str) -> UnsavedChoice:
        """Ask what to do with unsaved changes."""
        answer = QMessageBox.question(
            self.parent,
            "Unsaved changes",
            f"Save the changes made to {project_name}?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return "save"
        if answer == QMessageBox.StandardButton.Discard:
            return "discard"
        return "cancel"

    def ask_recover(self, project_name: str) -> bool:
        """Ask whether to recover an autosave newer than the project."""
        answer = QMessageBox.question(
            self.parent,
            "Recover unsaved changes",
            f"{project_name} has unsaved changes from a previous session. "
            "Recover them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return answer == QMessageBox.StandardButton.Yes

    def show_error(self, title: str, message: str) -> None:
        """Show an error."""
        QMessageBox.critical(self.parent, title, message)


class FileDialogParams(BaseModel):
    """Parameters of ``dialog.openFile`` and ``dialog.openFolder``."""

    title: str = "Open"
    filter: str = "All files (*)"
    start: str = ""


def register_dialog_methods(bridge: Bridge, parent: QWidget) -> None:
    """Register native file dialogs for the page: ``dialog.openFile/openFolder``."""

    def open_file(params: FileDialogParams) -> str | None:
        path, _ = QFileDialog.getOpenFileName(
            parent, params.title, params.start, params.filter
        )
        return path or None

    def open_folder(params: FileDialogParams) -> str | None:
        return (
            QFileDialog.getExistingDirectory(parent, params.title, params.start) or None
        )

    bridge.registry.add("dialog.openFile", open_file)
    bridge.registry.add("dialog.openFolder", open_folder)
