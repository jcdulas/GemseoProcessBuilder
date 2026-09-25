"""GEMSEO post-processings of the runs: ``postproc.*`` methods (SPEC § 12.3).

The post-processings run in the worker. The worker serves one request at a
time and GEMSEO cannot be interrupted, so cancelling a post-processing restarts
the worker; the half-written output folder has no ``settings.json`` and is not
listed.
"""

import shutil
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.scheme_handler import is_safe_path
from gemseo_process_builder.app.worker_client import WorkerClient
from gemseo_process_builder.app.worker_client import WorkerRequestError
from gemseo_process_builder.app.worker_client import WorkerUnavailableError
from gemseo_process_builder.app.worker_client import unwrap
from gemseo_process_builder.results.store import RunStore

LIST_TIMEOUT_S = 60.0
RUN_TIMEOUT_S = 3600.0
POSTPROC_FOLDER = "postproc"


class RunParams(BaseModel):
    """Parameters naming a run."""

    id: str


class PostprocParams(BaseModel):
    """Parameters of ``postproc.run``."""

    id: str
    name: str
    settings: dict[str, Any] = {}


class ResultParams(BaseModel):
    """Parameters naming the output of a post-processing."""

    id: str
    result: str


class PostprocController:
    """Run post-processings and manage their outputs."""

    def __init__(self, store: RunStore, bridge: Bridge, worker: WorkerClient) -> None:
        self.store = store
        self.bridge = bridge
        self.worker = worker
        self._running: str | None = None
        """The worker request of the post-processing being run."""
        self._cancelled = False

    def _folder(self, run_id: str) -> Path:
        folder = self.store.folder_of(run_id)
        if folder is None:
            raise BridgeError(
                ErrorCode.NOT_FOUND, f"The run {run_id} is not in the project."
            )
        return folder

    def _output(self, params: ResultParams) -> Path:
        if not is_safe_path(params.result) or "/" in params.result:
            raise BridgeError(ErrorCode.INVALID_PARAMS, "Invalid result name.")
        output = self._folder(params.id) / POSTPROC_FOLDER / params.result
        if not output.is_dir():
            raise BridgeError(ErrorCode.NOT_FOUND, "The result no longer exists.")
        return output

    def _call(self, method: str, params: dict[str, Any], timeout: float) -> Any:
        try:
            return self.worker.call(method, params, timeout=timeout)
        except WorkerRequestError as error:
            raise BridgeError(error.code, error.message) from None
        except WorkerUnavailableError as error:
            raise BridgeError(ErrorCode.WORKER_UNAVAILABLE, str(error)) from None

    def list_postprocessings(self, params: RunParams) -> Any:
        """The post-processings offered for a run, with their settings schemas."""
        return self._call(
            "postproc.list", {"folder": str(self._folder(params.id))}, LIST_TIMEOUT_S
        )

    def results(self, params: RunParams) -> Any:
        """The outputs of the post-processings already run on a run."""
        return self._call(
            "postproc.results", {"folder": str(self._folder(params.id))}, LIST_TIMEOUT_S
        )

    def run(self, params: PostprocParams) -> Any:
        """Run a post-processing and return its output (one at a time)."""
        if self._running is not None:
            raise BridgeError(
                ErrorCode.CONFLICT, "A post-processing is already running."
            )
        done = threading.Event()
        box: dict[str, Any] = {}
        self._cancelled = False

        def store(response: dict[str, Any]) -> None:
            box.update(response)
            done.set()

        self._running = self.worker.request(
            "postproc.run",
            {
                "folder": str(self._folder(params.id)),
                "name": params.name,
                "settings": params.settings,
            },
            store,
            RUN_TIMEOUT_S,
        )
        try:
            done.wait(RUN_TIMEOUT_S + 5)
            try:
                return unwrap(box)
            except WorkerRequestError as error:
                raise BridgeError(error.code, error.message) from None
            except WorkerUnavailableError as error:
                if self._cancelled:
                    raise BridgeError(
                        ErrorCode.CANCELLED, "The post-processing was cancelled."
                    ) from None
                raise BridgeError(ErrorCode.WORKER_UNAVAILABLE, str(error)) from None
        finally:
            self._running = None

    def cancel(self) -> None:
        """Stop the post-processing being run by restarting the worker."""
        if self._running is not None:
            self._cancelled = True
            self.worker.restart()

    def delete(self, params: ResultParams) -> None:
        """Delete the output of a post-processing."""
        shutil.rmtree(self._output(params))

    def reveal(self, params: ResultParams) -> None:
        """Open the output folder of a post-processing in the file manager."""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output(params))))

    def register(self) -> None:
        """Register the ``postproc.*`` methods."""
        registry = self.bridge.registry
        registry.add("postproc.list", self.list_postprocessings, background=True)
        registry.add("postproc.results", self.results, background=True)
        registry.add("postproc.run", self.run, background=True)
        registry.add("postproc.cancel", self.cancel)
        registry.add("postproc.delete", self.delete)
        registry.add("postproc.reveal", self.reveal)
