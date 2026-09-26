"""The open project: its file, its unsaved changes and its autosave."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from gemseo_process_builder.core.atomic_write import write_text_atomically
from gemseo_process_builder.core.document import Document
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.project_lock import LockOwner
from gemseo_process_builder.core.project_lock import acquire
from gemseo_process_builder.core.project_lock import owner_of
from gemseo_process_builder.core.project_lock import release
from gemseo_process_builder.core.serialization import dumps
from gemseo_process_builder.core.serialization import load_project
from gemseo_process_builder.core.serialization import loads
from gemseo_process_builder.core.serialization import project_name_from_path
from gemseo_process_builder.core.serialization import save_project

AUTOSAVE_SUFFIX = ".autosave"
AUTOSAVE_INTERVAL_MS = 2 * 60 * 1000


def autosave_path_for(project_path: Path) -> Path:
    """Return the autosave file of a project file."""
    return project_path.with_name(project_path.name + AUTOSAVE_SUFFIX)


def recovery_candidate(project_path: Path) -> Path | None:
    """Return the autosave of a project if it is newer than the project file."""
    autosave = autosave_path_for(project_path)
    if not autosave.exists():
        return None
    if project_path.exists() and (
        autosave.stat().st_mtime <= project_path.stat().st_mtime
    ):
        return None
    return autosave


class ProjectLockedError(Exception):
    """A project file that another application holds; the message is for the user."""


class ProjectSession:
    """The project being edited.

    Args:
        untitled_autosave: Where to autosave a project that was never saved.
        max_undo: The number of undo steps kept.
    """

    def __init__(self, untitled_autosave: Path, max_undo: int = 500) -> None:
        self.untitled_autosave = untitled_autosave
        self.document = Document(Project(), max_undo=max_undo)
        self.document.on_content_change(self.set_dirty)
        self.path: Path | None = None
        self.dirty = False
        self.ports_unknown = False
        """Whether the ports of the project are to be read again: a project
        read from a script only has the values typed on its inputs."""

        self.locked_by: LockOwner | None = None
        """Another application holding the project: it is then read-only."""

        self._listeners: list[Callable[[], None]] = []

    # State ---------------------------------------------------------------------

    @property
    def project(self) -> Project:
        """The project being edited."""
        return self.document.project

    @project.setter
    def project(self, project: Project) -> None:
        self.document.reset(project)

    @property
    def name(self) -> str:
        """The project name shown to the user."""
        return self.project.metadata.name

    @property
    def folder(self) -> Path:
        """The folder against which relative paths are resolved."""
        return self.path.parent if self.path else self.untitled_autosave.parent

    @property
    def autosave_path(self) -> Path:
        """The autosave file of the current project."""
        return autosave_path_for(self.path) if self.path else self.untitled_autosave

    def state(self) -> dict[str, Any]:
        """The state sent to the page."""
        return {
            "name": self.name,
            "path": str(self.path) if self.path else None,
            "dirty": self.dirty,
            "read_only": self.locked_by.describe() if self.locked_by else "",
        }

    def on_change(self, listener: Callable[[], None]) -> None:
        """Call ``listener`` whenever the project, its path or its state changes."""
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in self._listeners:
            listener()

    def set_dirty(self, dirty: bool = True) -> None:
        """Mark the project as modified (or not); listeners are always told."""
        self.dirty = dirty
        self._notify()

    # Lifecycle -----------------------------------------------------------------

    def _set_path(self, path: Path | None) -> None:
        """Change the project file, moving the lock from the old one to it."""
        if self.path is not None and self.locked_by is None:
            release(self.path)
        self.path = path
        self.locked_by = acquire(path) if path is not None else None

    def release_lock(self) -> None:
        """Let other applications edit the project (when closing)."""
        self._set_path(None)

    def new(self) -> None:
        """Replace the project by an empty, untitled one."""
        self.discard_autosave()
        self.project = Project()
        self._set_path(None)
        self.dirty = False
        self._notify()

    def open(self, path: Path, from_autosave: Path | None = None) -> None:
        """Open a project file.

        Args:
            path: The project file.
            from_autosave: An autosave to recover instead of the file content;
                the project is then marked as modified.

        Raises:
            ProjectFileError: When the file is not a valid project.
        """
        if from_autosave is None:
            project = load_project(path)
        else:
            project = loads(from_autosave.read_text(encoding="utf-8"), path.parent)
        self.discard_autosave()
        self.project = project
        self._set_path(path.resolve())
        self.dirty = from_autosave is not None
        self._notify()

    def adopt(self, project: Project) -> None:
        """Replace the project by one built elsewhere (read from a script).

        It has no project file yet: it is saved like a new project.
        """
        self.discard_autosave()
        self.ports_unknown = True
        self.project = project
        self._set_path(None)
        self.dirty = True
        self._notify()
        self.ports_unknown = False

    def recover_untitled(self) -> None:
        """Reload the autosave of an untitled project."""
        self.project = loads(
            self.untitled_autosave.read_text(encoding="utf-8"),
            self.untitled_autosave.parent,
        )
        self._set_path(None)
        self.dirty = True
        self._notify()

    def save(self, path: Path | None = None) -> Path:
        """Save the project, to ``path`` or to its current file.

        A project saved for the first time takes its name from the file name.

        Raises:
            ValueError: When the project has no file yet and no path is given.
            ProjectLockedError: When another application holds the file.
        """
        if path is None and self.path is None:
            msg = "The project has no file yet: a path is required."
            raise ValueError(msg)
        target = (path or self.path or Path()).resolve()
        owner = self.locked_by if target == self.path else owner_of(target)
        if owner is not None:
            msg = (
                f"{target.name} is open in {owner.describe()}: it is read-only "
                "here. Save it under another name to keep your changes."
            )
            raise ProjectLockedError(msg)
        if target != self.path:
            self.discard_autosave()  # The autosave of the previous location.
        if self.project.metadata.name in ("", "Untitled"):
            self.project.metadata.name = project_name_from_path(target)
        save_project(self.project, target)
        if target != self.path:
            self._set_path(target)
        self.discard_autosave()
        self.dirty = False
        self._notify()
        return target

    def write_autosave(self) -> bool:
        """Write the autosave file if there are unsaved changes.

        A read-only project has no autosave: it belongs to the other application.
        """
        if not self.dirty or self.locked_by is not None:
            return False
        write_text_atomically(self.autosave_path, dumps(self.project, self.folder))
        return True

    def discard_autosave(self) -> None:
        """Delete the autosave file of the current project."""
        self.autosave_path.unlink(missing_ok=True)
