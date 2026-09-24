"""The component catalog of the application (SPEC § 7.6).

The catalog folders come from the preferences (for every project) and from the
project settings. Their files are scanned by the worker; results are cached by
file modification time, so only new or changed files are scanned again. The
folders are watched and rescanned one second after a change.
"""

import json
import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QFileSystemWatcher
from PySide6.QtCore import QObject
from PySide6.QtCore import QRunnable
from PySide6.QtCore import QThreadPool
from PySide6.QtCore import QTimer
from PySide6.QtCore import Signal
from PySide6.QtCore import Slot

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.preferences import PreferencesStore
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.app.worker_client import WorkerClient
from gemseo_process_builder.catalog.models import FileScan
from gemseo_process_builder.catalog.scanner import catalog_files
from gemseo_process_builder.catalog.scanner import is_ignored

_LOGGER = logging.getLogger(__name__)

SCAN_TIMEOUT_S = 300.0
WATCH_DELAY_MS = 1000


class CatalogCache:
    """Scan results by file path, saved as JSON."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.scans: dict[str, FileScan] = {}
        if path is not None and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.scans = {
                    key: FileScan.model_validate(value) for key, value in data.items()
                }
            except (ValueError, TypeError):
                _LOGGER.warning("The catalog cache is invalid and was ignored.")

    def outdated(self, files: list[Path], force: bool = False) -> list[Path]:
        """The files never scanned, or changed since their last scan."""
        return [
            file
            for file in files
            if force
            or str(file) not in self.scans
            or self.scans[str(file)].mtime != file.stat().st_mtime
        ]

    def update(self, scans: list[FileScan], existing: list[Path]) -> None:
        """Store new results and forget the files that no longer exist."""
        for scan in scans:
            self.scans[scan.path] = scan
        kept = {str(file) for file in existing}
        self.scans = {key: value for key, value in self.scans.items() if key in kept}

    def save(self) -> None:
        """Write the cache file."""
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {key: scan.model_dump(mode="json") for key, scan in self.scans.items()}
        self.path.write_text(json.dumps(data), encoding="utf-8")


class _Scan(QRunnable):
    def __init__(self, service: "CatalogService", force: bool) -> None:
        super().__init__()
        self._service = service
        self._force = force

    def run(self) -> None:
        self._service._scan(self._force)


class CatalogService(QObject):
    """Keep the catalog up to date and publish it to the page."""

    _scan_done = Signal()

    def __init__(
        self,
        bridge: Bridge,
        worker: WorkerClient,
        preferences: PreferencesStore,
        session: ProjectSession,
        cache: CatalogCache,
    ) -> None:
        super().__init__()
        self.bridge = bridge
        self.worker = worker
        self.preferences = preferences
        self.session = session
        self.cache = cache
        self.scanning = False
        self._pending: bool | None = None
        self._errors: list[str] = []
        self._watcher = QFileSystemWatcher(self)
        self._watch_timer = QTimer(self)
        self._watch_timer.setSingleShot(True)
        self._watch_timer.setInterval(WATCH_DELAY_MS)
        self._watch_timer.timeout.connect(lambda: self.refresh())
        self._watcher.directoryChanged.connect(lambda _: self._watch_timer.start())
        self._watcher.fileChanged.connect(lambda _: self._watch_timer.start())
        self._scan_done.connect(self._finished)
        self._folders: list[str] = self.folders()

        worker.event_received.connect(self._worker_event)
        preferences.on_change(lambda old, new: self._folders_may_have_changed())
        session.on_change(self._folders_may_have_changed)

    # Folders -------------------------------------------------------------------

    def folders(self) -> list[str]:
        """The catalog folders: from the preferences, then from the project."""
        paths = [
            *self.preferences.preferences.catalog_paths,
            *self.session.project.settings.catalog_paths,
        ]
        unique: list[str] = []
        for path in paths:
            if path and path not in unique:
                unique.append(path)
        return unique

    def _folders_may_have_changed(self) -> None:
        folders = self.folders()
        if folders != self._folders:
            self._folders = folders
            self.refresh()

    def _watch(self) -> None:
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        paths = []
        for folder in self._folders:
            root = Path(folder)
            if root.is_dir():
                paths.append(str(root))
                paths.extend(
                    str(path)
                    for path in root.rglob("*")
                    if path.is_dir() and not is_ignored(path.relative_to(root))
                )
        if paths:
            self._watcher.addPaths(paths)

    # Scanning ------------------------------------------------------------------

    def _worker_event(self, name: str, payload: Any) -> None:
        if name == "gemseo_loaded":
            self.refresh()

    def refresh(self, force: bool = False) -> None:
        """Scan the new and changed files (all files if ``force``)."""
        if self.scanning:
            self._pending = bool(self._pending) or force
            return
        self.scanning = True
        self._publish()
        QThreadPool.globalInstance().start(_Scan(self, force))

    def _scan(self, force: bool) -> None:
        """Run in a pool thread."""
        errors: list[str] = []
        try:
            files = [
                file
                for folder in self._folders
                if Path(folder).is_dir()
                for file in catalog_files(Path(folder))
            ]
            outdated = self.cache.outdated(files, force)
            scans: list[FileScan] = []
            if outdated:
                results = self.worker.call(
                    "catalog.scan",
                    {"files": [str(file) for file in outdated]},
                    timeout=SCAN_TIMEOUT_S,
                )
                scans = [FileScan.model_validate(result) for result in results]
            self.cache.update(scans, files)
            self.cache.save()
        except Exception as error:
            _LOGGER.warning("The catalog could not be scanned: %s", error)
            errors.append(str(error))
        self._errors = errors
        self._scan_done.emit()

    @Slot()
    def _finished(self) -> None:
        self.scanning = False
        self._watch()
        self._publish()
        if self._pending is not None:
            force, self._pending = self._pending, None
            self.refresh(force)

    # Page ----------------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        """The catalog as shown by the Library panel."""
        folders = []
        for folder in self._folders:
            root = Path(folder)
            files = []
            for key, scan in sorted(self.cache.scans.items()):
                path = Path(key)
                if root in path.parents:
                    files.append(
                        {
                            "path": key,
                            "relative": path.relative_to(root).as_posix(),
                            "entries": [
                                entry.model_dump(mode="json") for entry in scan.entries
                            ],
                            "error": scan.error.model_dump(mode="json")
                            if scan.error
                            else None,
                        }
                    )
            folders.append({"path": folder, "exists": root.is_dir(), "files": files})
        return {"scanning": self.scanning, "folders": folders, "errors": self._errors}

    def _publish(self) -> None:
        self.bridge.emit_event("catalog.updated", self.state())

    def register(self) -> None:
        """Register ``catalog.list`` and ``catalog.refresh``."""
        self.bridge.registry.add("catalog.list", self.state)

        def refresh() -> dict[str, Any]:
            self.refresh(force=True)
            return self.state()

        self.bridge.registry.add("catalog.refresh", refresh)
