"""The runs of the project and their results: ``runs.*`` and ``results.*`` methods.

The index and the folders are handled here; reading results needs GEMSEO's
dependencies (NumPy, HDF5), so it happens in the worker.
"""

from pathlib import Path
from typing import Any
from typing import Literal

from pydantic import BaseModel
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.worker_client import WorkerClient
from gemseo_process_builder.app.worker_client import WorkerRequestError
from gemseo_process_builder.app.worker_client import WorkerUnavailableError
from gemseo_process_builder.results.store import RunStore
from gemseo_process_builder.results.store import RunStoreError

TIMEOUT_S = 120.0


class RunParams(BaseModel):
    """Parameters naming a run."""

    id: str


class FileParams(BaseModel):
    """Parameters of ``runs.openFile``."""

    id: str
    file: Literal["script.py", "run.log", "project.gpb.json"]


class RenameParams(BaseModel):
    """Parameters of ``runs.rename``."""

    id: str
    name: str


class ImportParams(BaseModel):
    """Parameters of ``runs.importOrphans``."""

    ids: list[str]


class QueryParams(BaseModel):
    """Parameters of ``results.rows`` and ``runs.exportCsv``."""

    id: str
    offset: int = 0
    limit: int = 500
    sort: dict[str, Any] | None = None
    filters: list[dict[str, Any]] = []
    names: list[str] | None = None
    path: str = ""
    """For ``runs.exportCsv``: the file, chosen with ``dialog.saveFile``."""


class HistoryParams(BaseModel):
    """Parameters of ``results.history``."""

    id: str
    names: list[str]


class ResultsController:
    """Runs panel and results queries."""

    def __init__(
        self,
        store: RunStore,
        bridge: Bridge,
        worker: WorkerClient,
    ) -> None:
        self.store = store
        self.bridge = bridge
        self.worker = worker

    def _folder(self, run_id: str) -> Path:
        for entry in self.store.entries():
            if entry["id"] == run_id:
                return Path(entry["folder"])
        raise BridgeError(
            ErrorCode.NOT_FOUND, f"The run {run_id} is not in the project."
        )

    def _call(self, method: str, params: dict[str, Any]) -> Any:
        try:
            return self.worker.call(method, params, timeout=TIMEOUT_S)
        except WorkerRequestError as error:
            raise BridgeError(error.code, error.message) from None
        except WorkerUnavailableError as error:
            raise BridgeError(ErrorCode.WORKER_UNAVAILABLE, str(error)) from None

    def _changed(self) -> None:
        self.bridge.emit_event("runs.changed", None)

    # Runs panel ----------------------------------------------------------------

    def folder(self, params: RunParams) -> str:
        """The folder of a run (to suggest where to export its results)."""
        return str(self._folder(params.id))

    def list_runs(self) -> dict[str, Any]:
        """The runs of the project, and the run folders it does not list."""
        return {"runs": self.store.entries(), "orphans": self.store.orphans()}

    def rename(self, params: RenameParams) -> dict[str, Any]:
        """Give a run a display name."""
        try:
            info = self.store.rename(params.id, params.name)
        except RunStoreError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        self._changed()
        return info.model_dump(mode="json")

    def delete(self, params: RunParams) -> None:
        """Delete a run and its folder (the page asks for confirmation)."""
        try:
            self.store.delete(params.id)
        except RunStoreError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        finally:
            self._changed()

    def import_orphans(self, params: ImportParams) -> int:
        """Add run folders found on disk to the project."""
        added = self.store.import_orphans(params.ids)
        self._changed()
        return added

    def forget_missing(self) -> int:
        """Remove the runs whose folder is missing from the project."""
        removed = self.store.forget_missing()
        self._changed()
        return removed

    def reveal(self, params: RunParams) -> None:
        """Open the folder of a run in the file manager."""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._folder(params.id))))

    def open_file(self, params: FileParams) -> None:
        """Open a file of a run with the application the system chooses."""
        path = self._folder(params.id) / params.file
        if not path.exists():
            raise BridgeError(ErrorCode.NOT_FOUND, f"The run has no {params.file}.")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def export_csv(self, params: QueryParams) -> dict[str, Any]:
        """Export the results of a run to a CSV file with one header line."""
        folder = self._folder(params.id)
        if not params.path:
            raise BridgeError(ErrorCode.INVALID_PARAMS, "Choose the CSV file first.")
        path = Path(params.path)
        count = self._call(
            "results.export_csv",
            {
                "folder": str(folder),
                "path": str(path),
                "names": params.names,
                "sort": params.sort,
                "filters": params.filters,
            },
        )
        return {"path": str(path), "rows": count}

    # Results -------------------------------------------------------------------

    def summary(self, params: RunParams) -> Any:
        """``run.json`` with the size of the results."""
        return self._call("results.summary", {"folder": str(self._folder(params.id))})

    def columns(self, params: RunParams) -> Any:
        """The columns of the results, with their roles."""
        return self._call("results.columns", {"folder": str(self._folder(params.id))})

    def rows(self, params: QueryParams) -> Any:
        """A page of rows, sorted and filtered."""
        return self._call(
            "results.rows",
            {
                "folder": str(self._folder(params.id)),
                "offset": params.offset,
                "limit": params.limit,
                "sort": params.sort,
                "filters": params.filters,
            },
        )

    def history(self, params: HistoryParams) -> Any:
        """Some columns in evaluation order."""
        return self._call(
            "results.history",
            {"folder": str(self._folder(params.id)), "names": params.names},
        )

    def register(self) -> None:
        """Register the ``runs.*`` and ``results.*`` methods."""
        registry = self.bridge.registry
        registry.add("runs.list", self.list_runs)
        registry.add("runs.folder", self.folder)
        registry.add("runs.rename", self.rename)
        registry.add("runs.delete", self.delete)
        registry.add("runs.importOrphans", self.import_orphans)
        registry.add("runs.forgetMissing", self.forget_missing)
        registry.add("runs.reveal", self.reveal)
        registry.add("runs.openFile", self.open_file)
        registry.add("runs.exportCsv", self.export_csv, background=True)
        registry.add("results.summary", self.summary, background=True)
        registry.add("results.columns", self.columns, background=True)
        registry.add("results.rows", self.rows, background=True)
        registry.add("results.history", self.history, background=True)
