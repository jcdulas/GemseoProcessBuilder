"""The 3D view of ``nastran_view`` opened for evaluations of a run (SPEC § 12.2).

``nastran_view`` is another application, in its own window and process: the
page of this one never holds a WebGL or canvas view. The worker, which runs
with the Python of the runs, says whether ``nastran_view`` is installed there and
which sizing folder of ``gemseo_nastran`` each evaluation has; the command is
started from here, by an argument list, never through a shell.
"""

import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic import Field

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.preferences import PreferencesStore
from gemseo_process_builder.app.worker_client import WorkerClient
from gemseo_process_builder.app.worker_client import WorkerRequestError
from gemseo_process_builder.app.worker_client import WorkerUnavailableError
from gemseo_process_builder.results.store import RunStore

TIMEOUT_S = 60.0


class StateParams(BaseModel):
    """Parameters of ``view3d.state``."""

    run_id: str


class OpenParams(BaseModel):
    """Parameters of ``view3d.open``."""

    run_id: str
    evaluations: list[int] = Field(min_length=1, max_length=2)
    """One evaluation to open, or two to compare."""


def view_command(python: str, folders: list[str], title: str) -> list[str]:
    """The command of ``nastran_view`` for one folder, or two compared."""
    command = [python, "-m", "nastran_view", folders[0]]
    if len(folders) > 1:
        command += ["--compare", folders[1]]
    return [*command, "--title", title]


class View3dService:
    """Open evaluations of a run in ``nastran_view``."""

    def __init__(
        self,
        store: RunStore,
        bridge: Bridge,
        worker: WorkerClient,
        preferences: PreferencesStore,
    ) -> None:
        self.store = store
        self.bridge = bridge
        self.worker = worker
        self.preferences = preferences

    def _folder(self, run_id: str) -> Path:
        for entry in self.store.entries():
            if entry["id"] == run_id:
                return Path(entry["folder"])
        msg = f"The run {run_id} is not in the project."
        raise BridgeError(ErrorCode.NOT_FOUND, msg)

    def state(self, params: StateParams) -> dict[str, Any]:
        """Whether ``nastran_view`` is installed, and the folder of each evaluation."""
        try:
            result: dict[str, Any] = self.worker.call(
                "view3d.state",
                {"folder": str(self._folder(params.run_id))},
                timeout=TIMEOUT_S,
            )
        except WorkerUnavailableError as error:
            raise BridgeError(ErrorCode.WORKER_UNAVAILABLE, str(error)) from None
        except WorkerRequestError as error:
            raise BridgeError(error.code, error.message) from None
        return result

    def open(self, params: OpenParams) -> dict[str, Any]:
        """Start ``nastran_view`` on one evaluation, or two compared."""
        state = self.state(StateParams(run_id=params.run_id))
        if not state["available"]:
            raise BridgeError(ErrorCode.CONFLICT, state["reason"])
        folders = [state["folders"].get(str(number)) for number in params.evaluations]
        missing = [
            str(number)
            for number, folder in zip(params.evaluations, folders, strict=True)
            if not folder
        ]
        if missing:
            msg = (
                f"No sizing folder of gemseo_nastran for evaluation "
                f"{', '.join(missing)} in {state['store']}."
            )
            raise BridgeError(ErrorCode.NOT_FOUND, msg)
        numbers = " and ".join(str(number) for number in params.evaluations)
        title = (
            f"{params.run_id}: evaluation{'s' if len(folders) > 1 else ''} {numbers}"
        )
        python = self.preferences.preferences.python_interpreter or sys.executable
        command = view_command(python, [str(folder) for folder in folders], title)
        try:
            subprocess.Popen(command, close_fds=True)
        except OSError as error:
            msg = f"nastran_view could not be started: {error}"
            raise BridgeError(ErrorCode.INTERNAL, msg) from None
        return {"command": command}

    def register(self) -> None:
        """Register ``view3d.state`` and ``view3d.open``."""
        registry = self.bridge.registry
        registry.add("view3d.state", self.state, background=True)
        registry.add("view3d.open", self.open, background=True)
