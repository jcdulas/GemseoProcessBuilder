"""Project lifecycle: ``project.*`` methods and File menu behavior."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.dialogs import Dialogs
from gemseo_process_builder.app.preferences import PreferencesStore
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.app.project_session import recovery_candidate
from gemseo_process_builder.core.migrations import ProjectFileError

_LOGGER = logging.getLogger(__name__)

INVALID_FILE = "invalid_file"


class OpenParams(BaseModel):
    """Parameters of ``project.open``; without a path, a file dialog is shown."""

    path: str | None = None


class ProjectController:
    """Open, save and close projects, asking the user when needed."""

    def __init__(
        self,
        session: ProjectSession,
        bridge: Bridge,
        dialogs: Dialogs,
        preferences: PreferencesStore,
    ) -> None:
        self.session = session
        self.bridge = bridge
        self.dialogs = dialogs
        self.preferences = preferences
        self._recent_listeners: list[Callable[[list[str]], None]] = []
        session.on_change(self._state_changed)

    # Helpers -------------------------------------------------------------------

    def _state_changed(self) -> None:
        self.bridge.emit_event("project.changed", self.session.state())

    def _document_replaced(self) -> None:
        self.bridge.emit_event("document.reset", self.document())

    def on_recent_changed(self, listener: Callable[[list[str]], None]) -> None:
        """Call ``listener`` with the recent projects whenever they change."""
        self._recent_listeners.append(listener)
        listener(self.preferences.preferences.recent_projects)

    def _remember(self, path: Path) -> None:
        self.preferences.add_recent_project(str(path))
        for listener in self._recent_listeners:
            listener(self.preferences.preferences.recent_projects)

    def confirm_discard(self) -> bool:
        """Deal with unsaved changes; return whether the current project can go."""
        if not self.session.dirty:
            return True
        choice = self.dialogs.ask_unsaved_changes(self.session.name)
        if choice == "cancel":
            return False
        if choice == "save":
            return self.save()["saved"] is True
        return True

    def confirm_close(self) -> bool:
        """Deal with unsaved changes before quitting the application."""
        if not self.confirm_discard():
            return False
        self.session.discard_autosave()
        return True

    def open_recent(self, path: str) -> None:
        """Open a recent project from the native menu, showing errors in a dialog."""
        try:
            self.open(OpenParams(path=path))
        except BridgeError as error:
            self.dialogs.show_error("Cannot open the project", error.message)

    # Methods -------------------------------------------------------------------

    def document(self) -> dict[str, Any]:
        """Return the whole project as JSON data (``project.get``)."""
        return self.session.project.model_dump(mode="json")

    def state(self) -> dict[str, Any]:
        """Return the name, path and modified flag (``project.state``)."""
        return self.session.state()

    def new(self) -> dict[str, Any]:
        """Start an empty project (``project.new``)."""
        if not self.confirm_discard():
            return {"cancelled": True}
        self.session.new()
        self._document_replaced()
        return {"cancelled": False}

    def open(self, params: OpenParams) -> dict[str, Any]:
        """Open a project file (``project.open``)."""
        if not self.confirm_discard():
            return {"cancelled": True}
        path = Path(params.path) if params.path else self.dialogs.ask_open_project()
        if path is None:
            return {"cancelled": True}
        return self.open_path(path)

    def open_path(self, path: Path) -> dict[str, Any]:
        """Open a project file without asking about the current project."""
        autosave = recovery_candidate(path)
        if autosave is not None and not self.dialogs.ask_recover(path.name):
            autosave.unlink()
            autosave = None
        try:
            self.session.open(path, from_autosave=autosave)
        except ProjectFileError as error:
            raise BridgeError(INVALID_FILE, str(error)) from None
        self._remember(self.session.path or path)
        self._document_replaced()
        _LOGGER.info("Opened %s", path)
        return {"cancelled": False}

    def save(self) -> dict[str, Any]:
        """Save the project to its file, or ask for one (``project.save``)."""
        if self.session.path is None:
            return self.save_as()
        self.session.save()
        _LOGGER.info("Saved %s", self.session.path)
        return {"saved": True}

    def save_as(self) -> dict[str, Any]:
        """Save the project to a new file (``project.saveAs``)."""
        path = self.dialogs.ask_save_project(self.session.name)
        if path is None:
            return {"saved": False}
        saved = self.session.save(path)
        self._remember(saved)
        self._state_changed()
        _LOGGER.info("Saved %s", saved)
        return {"saved": True}

    def close(self) -> dict[str, Any]:
        """Close the project, leaving an empty one (``project.close``)."""
        return self.new()

    def recent(self) -> list[str]:
        """Return the recent projects (``project.recent``)."""
        return self.preferences.preferences.recent_projects

    def autosave(self) -> None:
        """Write the autosave file if needed (called by a timer)."""
        try:
            if self.session.write_autosave():
                _LOGGER.debug("Autosaved to %s", self.session.autosave_path)
        except OSError as error:
            _LOGGER.warning("Autosave failed: %s", error)

    def recover_untitled_at_startup(self) -> None:
        """Offer to recover an untitled project left by a previous session."""
        if not self.session.untitled_autosave.exists():
            return
        if self.dialogs.ask_recover("The untitled project"):
            try:
                self.session.recover_untitled()
            except ProjectFileError as error:
                self.dialogs.show_error("Recovery failed", str(error))
                return
            self._document_replaced()
        else:
            self.session.untitled_autosave.unlink()

    def register(self) -> None:
        """Register the ``project.*`` methods."""
        registry = self.bridge.registry
        registry.add("project.get", self.document)
        registry.add("project.state", self.state)
        registry.add("project.new", self.new)
        registry.add("project.open", self.open)
        registry.add("project.save", self.save)
        registry.add("project.saveAs", self.save_as)
        registry.add("project.close", self.close)
        registry.add("project.recent", self.recent)
