"""The open project: its file, its unsaved changes and its autosave."""

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gemseo_process_builder.codegen.generator import CodegenError
from gemseo_process_builder.codegen.generator import project_script
from gemseo_process_builder.core.atomic_write import write_text_atomically
from gemseo_process_builder.core.document import Document
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.project_lock import LockOwner
from gemseo_process_builder.core.project_lock import acquire
from gemseo_process_builder.core.project_lock import owner_of
from gemseo_process_builder.core.project_lock import release
from gemseo_process_builder.core.script_project import backup_file
from gemseo_process_builder.core.script_project import merge_script
from gemseo_process_builder.core.script_project import side_data
from gemseo_process_builder.core.script_project import side_file
from gemseo_process_builder.core.serialization import dumps
from gemseo_process_builder.core.serialization import load_project
from gemseo_process_builder.core.serialization import loads
from gemseo_process_builder.core.serialization import project_name_from_path
from gemseo_process_builder.core.serialization import project_to_data
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

        self.save_notes: list[str] = []
        """What the last save wants the user to know (saved as a script)."""

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

    def adopt(self, project: Project, script: Path | None = None) -> None:
        """Replace the project by one read from a GEMSEO script.

        Args:
            project: The project read.
            script: The script, which becomes the project file: saving writes
                it again. Without it, the project is saved like a new one.
        """
        self.discard_autosave()
        self.ports_unknown = True
        self.project = project
        self._set_path(script.resolve() if script else None)
        self.dirty = True
        self._notify()
        self.ports_unknown = False

    def open_script(self, script: Path, data: dict[str, Any]) -> None:
        """Open a project saved as a script, from its side file (unchanged)."""
        project = loads(json.dumps(data), script.parent)
        self.discard_autosave()
        self.project = project
        self._set_path(script.resolve())
        self.dirty = False
        self._notify()

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
        if target.suffix == ".py":
            self.save_notes = save_as_script(self.project, target)
        else:
            self.save_notes = []
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


def _write_hidden(path: Path, text: str) -> None:
    """Write a file hidden in the file manager (a dot file elsewhere)."""
    if sys.platform == "win32":
        import ctypes

        # A hidden file cannot be replaced: it is shown during the write.
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x80)  # NORMAL
        write_text_atomically(path, text)
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)  # HIDDEN
        return
    write_text_atomically(path, text)


def save_as_script(project: Project, script: Path) -> list[str]:
    """Save a project as a GEMSEO script and its side file.

    The application rewrites its functions and keeps the code the user added.
    When the project cannot be written as a script yet (an empty model, a
    driver not set up), the script is left as it is and the side file keeps
    the whole project.

    Returns:
        What the user should know.
    """
    notes: list[str] = []
    existing = script.read_text(encoding="utf-8") if script.exists() else None
    try:
        generated = project_script(project, script)
    except CodegenError as error:
        text = existing or f'"""{project.metadata.name}: not complete yet."""\n'
        if existing is None:
            write_text_atomically(script, text)
        notes.append(
            f"The script is not written yet ({error}): the project is kept next "
            f"to it, in {side_file(script).name}."
        )
    else:
        merged = merge_script(generated, existing)
        backup = backup_file(script)
        if merged.replaced and existing and not backup.exists():
            write_text_atomically(backup, existing)
            notes.append(
                f"The study of {script.name} is now written by the application; "
                f"your original script is kept in {backup.name}."
            )
        if merged.kept:
            notes.append(f"Kept from your script: {', '.join(merged.kept)}.")
        text = merged.source
        write_text_atomically(script, text)
    _write_hidden(
        side_file(script), side_data(project_to_data(project, script.parent), text)
    )
    return notes
