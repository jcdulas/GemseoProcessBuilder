"""The open project: its file, its unsaved changes and its autosave."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from gemseo_process_builder.core.document import Document
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.serialization import dumps
from gemseo_process_builder.core.serialization import load_project
from gemseo_process_builder.core.serialization import loads
from gemseo_process_builder.core.serialization import project_name_from_path
from gemseo_process_builder.core.serialization import save_project
from gemseo_process_builder.core.serialization import write_text_atomically

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
        }

    def on_change(self, listener: Callable[[], None]) -> None:
        """Call ``listener`` whenever the project, its path or its state changes."""
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in self._listeners:
            listener()

    def set_dirty(self, dirty: bool = True) -> None:
        """Mark the project as modified (or not)."""
        if self.dirty != dirty:
            self.dirty = dirty
            self._notify()

    # Lifecycle -----------------------------------------------------------------

    def new(self) -> None:
        """Replace the project by an empty, untitled one."""
        self.discard_autosave()
        self.project = Project()
        self.path = None
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
        self.path = path.resolve()
        self.dirty = from_autosave is not None
        self._notify()

    def recover_untitled(self) -> None:
        """Reload the autosave of an untitled project."""
        self.project = loads(
            self.untitled_autosave.read_text(encoding="utf-8"),
            self.untitled_autosave.parent,
        )
        self.path = None
        self.dirty = True
        self._notify()

    def save(self, path: Path | None = None) -> Path:
        """Save the project, to ``path`` or to its current file.

        A project saved for the first time takes its name from the file name.

        Raises:
            ValueError: When the project has no file yet and no path is given.
        """
        if path is None and self.path is None:
            msg = "The project has no file yet: a path is required."
            raise ValueError(msg)
        target = (path or self.path or Path()).resolve()
        if target != self.path:
            self.discard_autosave()  # The autosave of the previous location.
        if self.project.metadata.name in ("", "Untitled"):
            self.project.metadata.name = project_name_from_path(target)
        save_project(self.project, target)
        self.path = target
        self.discard_autosave()
        self.dirty = False
        self._notify()
        return target

    def write_autosave(self) -> bool:
        """Write the autosave file if there are unsaved changes."""
        if not self.dirty:
            return False
        write_text_atomically(self.autosave_path, dumps(self.project, self.folder))
        return True

    def discard_autosave(self) -> None:
        """Delete the autosave file of the current project."""
        self.autosave_path.unlink(missing_ok=True)
