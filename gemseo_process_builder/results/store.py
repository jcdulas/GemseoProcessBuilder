"""The runs of a project: their folders, ``run.json`` files and index (SPEC § 12.1).

The project lists its runs (``Project.runs``); each run lives in its own
folder, under ``<project>.runs/`` by default. The index is not part of the
undo history: changing it only marks the project as modified.
"""

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.core.model import RunRef
from gemseo_process_builder.results.models import RunInfo
from gemseo_process_builder.results.models import read_info
from gemseo_process_builder.results.models import write_info


class RunStoreError(Exception):
    """A run cannot be changed; the message is for the user."""


class RunStore:
    """The runs of the current project."""

    def __init__(self, session: ProjectSession) -> None:
        self.session = session
        self.deleted_listeners: list[Callable[[str], None]] = []
        """Called with the id of each deleted run."""

    def folder(self) -> Path:
        """The folder holding the runs of the project."""
        runs_dir = self.session.project.settings.runs_dir
        if runs_dir:
            folder = Path(runs_dir)
            return folder if folder.is_absolute() else self.session.folder / folder
        return self.session.folder / f"{self.session.name}.runs"

    def run_folder(self, ref: RunRef) -> Path:
        """The folder of an indexed run."""
        path = Path(ref.run_path)
        return path if path.is_absolute() else self.session.folder / path

    def folder_of(self, run_id: str) -> Path | None:
        """The folder of an indexed run, ``None`` when the project has no such run."""
        for ref in self.session.project.runs:
            if ref.id == run_id:
                return self.run_folder(ref)
        return None

    def _relative(self, folder: Path) -> str:
        try:
            return folder.relative_to(self.session.folder).as_posix()
        except ValueError:
            return str(folder)

    def _ref(self, run_id: str) -> RunRef:
        for ref in self.session.project.runs:
            if ref.id == run_id:
                return ref
        msg = f"The run {run_id} is not in the project."
        raise RunStoreError(msg)

    # Index -------------------------------------------------------------------

    def add(self, info: RunInfo, folder: Path) -> None:
        """Index a new run (the project becomes modified)."""
        if any(ref.id == info.id for ref in self.session.project.runs):
            return
        self.session.project.runs.append(
            RunRef(id=info.id, driver=info.driver, run_path=self._relative(folder))
        )
        self.session.set_dirty()

    def entries(self) -> list[dict[str, Any]]:
        """The indexed runs with their ``run.json``; missing folders are flagged."""
        entries = []
        for ref in self.session.project.runs:
            folder = self.run_folder(ref)
            info = read_info(folder)
            entry: dict[str, Any] = {
                "id": ref.id,
                "driver": ref.driver,
                "folder": str(folder),
                "missing": info is None,
            }
            if info is not None:
                entry.update(info.model_dump(mode="json"))
            entries.append(entry)
        return entries

    def orphans(self) -> list[dict[str, Any]]:
        """Run folders on disk that the project does not list."""
        root = self.folder()
        if not root.is_dir():
            return []
        indexed = {self.run_folder(ref).resolve() for ref in self.session.project.runs}
        found = []
        for folder in sorted(root.iterdir()):
            if folder.is_dir() and folder.resolve() not in indexed:
                info = read_info(folder)
                if info is not None:
                    found.append(
                        {**info.model_dump(mode="json"), "folder": str(folder)}
                    )
        return found

    def import_orphans(self, run_ids: list[str]) -> int:
        """Index run folders found on disk; return how many were added."""
        added = 0
        for orphan in self.orphans():
            if orphan["id"] in run_ids:
                info = RunInfo.model_validate(orphan)
                self.add(info, Path(orphan["folder"]))
                added += 1
        return added

    # Changes -----------------------------------------------------------------

    def rename(self, run_id: str, name: str) -> RunInfo:
        """Give a run a display name, stored in its ``run.json``."""
        folder = self.run_folder(self._ref(run_id))
        info = read_info(folder)
        if info is None:
            msg = f"The folder of {run_id} is missing: the run cannot be renamed."
            raise RunStoreError(msg)
        info.name = name.strip()
        write_info(folder, info)
        return info

    def delete(self, run_id: str) -> None:
        """Remove a run from the index, then delete its folder."""
        ref = self._ref(run_id)
        folder = self.run_folder(ref)
        self.session.project.runs.remove(ref)
        self.session.set_dirty()
        for listener in self.deleted_listeners:
            listener(run_id)
        if folder.exists():
            try:
                shutil.rmtree(folder)
            except OSError as error:
                msg = (
                    f"The run was removed from the project, but its folder "
                    f"{folder} could not be deleted: {error}"
                )
                raise RunStoreError(msg) from None

    def forget_missing(self) -> int:
        """Remove the runs whose folder is missing from the index."""
        missing = [
            ref
            for ref in self.session.project.runs
            if read_info(self.run_folder(ref)) is None
        ]
        for ref in missing:
            self.session.project.runs.remove(ref)
        if missing:
            self.session.set_dirty()
        return len(missing)
