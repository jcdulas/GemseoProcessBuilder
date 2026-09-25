"""Runs of drivers, each in its own runner process (SPEC § 11.1 to § 11.4).

Launch sequence: static validation, then a run folder with a snapshot of the
project, the generated script and its mapping, then a dry run in the worker,
then the runner process. The runner reports JSON-lines events, forwarded to
the page as ``run.event``; ``run.json`` in the run folder follows the status.
"""

import contextlib
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil
from PySide6.QtCore import QObject
from PySide6.QtCore import QProcess
from PySide6.QtCore import QProcessEnvironment
from PySide6.QtCore import QTimer
from PySide6.QtCore import Signal

from gemseo_process_builder import __version__
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.preferences import PreferencesStore
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.app.worker_client import PACKAGE_PARENT
from gemseo_process_builder.app.worker_client import WorkerClient
from gemseo_process_builder.app.worker_client import WorkerRequestError
from gemseo_process_builder.app.worker_client import WorkerUnavailableError
from gemseo_process_builder.app.worker_client import unwrap
from gemseo_process_builder.codegen.generator import CodegenError
from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.core.model import ContainerNode
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.model import path_of
from gemseo_process_builder.core.serialization import dumps
from gemseo_process_builder.core.validation import Problem
from gemseo_process_builder.results.models import RunInfo
from gemseo_process_builder.results.models import RunSummary
from gemseo_process_builder.results.models import VariableInfo
from gemseo_process_builder.results.models import write_info
from gemseo_process_builder.results.store import RunStore
from gemseo_process_builder.workers.protocol import decode
from gemseo_process_builder.workers.protocol import encode

_LOGGER = logging.getLogger(__name__)
_RUN_LOGGER = logging.getLogger("gemseo_process_builder.run")

RUNNER_MODULE = "gemseo_process_builder.runner"
DRY_RUN_TIMEOUT_S = 120.0
FINAL_STATES = ("completed", "stopped", "failed", "killed")


class RunError(Exception):
    """A run cannot start; the message is for the user."""


@dataclass
class Run:
    """A run and its process."""

    id: str
    target: str
    target_name: str
    folder: Path
    status: str = "preparing"
    created: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    started: str | None = None
    finished: str | None = None
    pid: int | None = None
    error: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    variables: list[dict[str, Any]] = field(default_factory=list)
    versions: dict[str, str] = field(default_factory=dict)
    driver_path: str = ""
    process: QProcess | None = None
    buffer: bytes = b""
    stop_timer: QTimer | None = None
    kill_requested: bool = False
    locked: list[str] = field(default_factory=list)
    """The nodes that cannot be edited during the run."""

    def to_info(self) -> RunInfo:
        """The content of ``run.json``."""
        duration = None
        if self.started and self.finished:
            elapsed = datetime.fromisoformat(self.finished) - datetime.fromisoformat(
                self.started
            )
            duration = elapsed.total_seconds()
        return RunInfo(
            id=self.id,
            driver=self.target,
            driver_name=self.target_name,
            driver_path=self.driver_path,
            status=self.status,  # type: ignore[arg-type]
            created=self.created,
            started=self.started,
            finished=self.finished,
            duration_s=duration,
            pid=self.pid,
            error=self.error,
            versions={"app": __version__, **self.versions},
            summary=RunSummary.model_validate(self.summary),
            variables=[VariableInfo.model_validate(v) for v in self.variables],
        )

    def to_dict(self) -> dict[str, Any]:
        """``run.json`` as sent to the page."""
        return self.to_info().model_dump(mode="json")


def new_run_id(folder: Path, now: datetime | None = None) -> str:
    """``r-YYYYMMDD-HHMMSS``, with ``-2``, ``-3``… if the folder exists."""
    base = (now or datetime.now()).strftime("r-%Y%m%d-%H%M%S")
    run_id, index = base, 2
    while (folder / run_id).exists():
        run_id, index = f"{base}-{index}", index + 1
    return run_id


def kill_tree(pid: int) -> None:
    """Kill a process and all its children (``n_processes`` workers included)."""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    processes = [*parent.children(recursive=True), parent]
    for process in processes:
        with contextlib.suppress(psutil.NoSuchProcess):
            process.kill()
    psutil.wait_procs(processes, timeout=3)


class RunManager(QObject):
    """Start, follow and stop runs."""

    run_changed = Signal(str)
    """Emitted with the run id when the status of a run changes."""

    def __init__(
        self,
        session: ProjectSession,
        bridge: Bridge,
        worker: WorkerClient,
        preferences: PreferencesStore,
        validate: Callable[[], list[Problem]],
    ) -> None:
        super().__init__()
        self.session = session
        self.bridge = bridge
        self.worker = worker
        self.preferences = preferences
        self.validate = validate
        self.runs: dict[str, Run] = {}
        self.store = RunStore(session)
        self.runner_command: list[str] | None = None
        """Replaces ``[python, -m, runner]`` (tests use a fake runner)."""

    # Start ---------------------------------------------------------------------

    def active(self) -> list[Run]:
        """The runs not finished yet."""
        return [run for run in self.runs.values() if run.status not in FINAL_STATES]

    def start(self, target_id: str) -> Run:
        """Prepare a run and start its dry run; the runner starts after it.

        Raises:
            RunError: When the run cannot start.
        """
        project = self.session.project
        target = project.find(target_id)
        if not isinstance(target, ContainerNode):
            msg = "Choose a driver (or the model) to run."
            raise RunError(msg)
        if self.active() and not self.preferences.preferences.allow_concurrent_runs:
            msg = (
                "A run is in progress: stop it first, or allow concurrent runs "
                "in the preferences."
            )
            raise RunError(msg)
        if any(run.target == target_id for run in self.active()):
            msg = f"{target.name} is already running."
            raise RunError(msg)
        subtree = {node.id for node, _ in iter_nodes(target)}
        errors = [
            problem
            for problem in self.validate()
            if problem.level == "error"
            and (problem.node in subtree or not problem.node)
        ]
        if errors:
            msg = (
                f"Fix the {len(errors)} errors listed in Problems "
                f"before running {target.name}."
            )
            raise RunError(msg)
        try:
            script = generate(project, target_id, project_file="project.gpb.json")
        except CodegenError as error:
            raise RunError(str(error)) from None

        runs_folder = self.store.folder()
        folder = runs_folder / new_run_id(runs_folder)
        folder.mkdir(parents=True)
        run = Run(folder.name, target_id, target.name, folder)
        run.driver_path = path_of(project, target_id)
        (folder / "project.gpb.json").write_text(
            dumps(project, folder), encoding="utf-8"
        )
        (folder / "script.py").write_text(script.source, encoding="utf-8", newline="\n")
        (folder / "script.gpb-map.json").write_text(
            script.mapping_json(), encoding="utf-8"
        )
        self.runs[run.id] = run
        self._lock(run)
        self._save(run)
        self.store.add(run.to_info(), folder)
        self.bridge.emit_event("run.started", run.to_dict())
        _RUN_LOGGER.info("Run %s of %s: checking the script", run.id, target.name)
        self.worker.request(
            "codegen.dry_run",
            {"source": script.source, "mapping": script.mapping},
            lambda response: self._dry_run_done(run, response),
            timeout=DRY_RUN_TIMEOUT_S,
        )
        return run

    def _dry_run_done(self, run: Run, response: dict[str, Any]) -> None:
        try:
            issues = unwrap(response)
        except (WorkerRequestError, WorkerUnavailableError) as error:
            self._finish(run, "failed", error=f"The dry run failed: {error}")
            return
        if issues:
            self._finish(
                run, "failed", error=f"The dry run failed: {issues[0]['message']}"
            )
            return
        self._start_process(run)

    def _start_process(self, run: Run) -> None:
        process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        paths = [PACKAGE_PARENT]
        if environment.contains("PYTHONPATH"):
            paths.append(environment.value("PYTHONPATH"))
        environment.insert(
            "PYTHONPATH", (";" if sys.platform == "win32" else ":").join(paths)
        )
        environment.insert("PYTHONUNBUFFERED", "1")
        environment.insert("PYTHONIOENCODING", "utf-8")
        process.setProcessEnvironment(environment)
        process.setWorkingDirectory(str(run.folder))
        process.readyReadStandardOutput.connect(lambda: self._read_stdout(run))
        process.readyReadStandardError.connect(lambda: self._read_stderr(run))
        process.finished.connect(lambda code, status: self._process_finished(run, code))
        process.errorOccurred.connect(lambda error: self._process_error(run, error))
        run.process = process
        run.status = "running"
        run.started = datetime.now().isoformat(timespec="seconds")
        self._save(run)
        command = self.runner_command or [
            self.preferences.preferences.python_interpreter or sys.executable,
            "-m",
            RUNNER_MODULE,
        ]
        process.start(command[0], [*command[1:], str(run.folder)])

    # Events --------------------------------------------------------------------

    def _read_stdout(self, run: Run) -> None:
        if run.process is None:
            return
        run.buffer += bytes(run.process.readAllStandardOutput().data())
        *lines, run.buffer = run.buffer.split(b"\n")
        for line in lines:
            message = decode(line.decode("utf-8", errors="replace"))
            if message is not None and "event" in message:
                self._handle(run, message["event"], message.get("payload"))

    def _read_stderr(self, run: Run) -> None:
        if run.process is None:
            return
        text = bytes(run.process.readAllStandardError().data()).decode(
            "utf-8", errors="replace"
        )
        for line in text.splitlines():
            if line.strip():
                self._log(run, "WARNING", line)

    def _handle(self, run: Run, event: str, payload: Any) -> None:
        if event == "started":
            run.pid = payload.get("pid")
            self._save(run)
        elif event == "log":
            self._log(run, payload.get("level", "INFO"), payload.get("message", ""))
        elif event == "batch" and payload.get("event") == "log":
            for item in payload.get("items", []):
                if "message" in item:
                    self._log(run, item.get("level", "INFO"), item["message"])
        elif event == "finished":
            run.summary = payload.get("summary") or {}
            run.variables = payload.get("variables") or []
            run.versions = payload.get("versions") or {}
            self._finish(
                run, payload.get("state", "failed"), error=payload.get("error")
            )
            return
        self.bridge.emit_event(
            "run.event", {"run_id": run.id, "event": event, "payload": payload}
        )

    def _log(self, run: Run, level: str, message: str) -> None:
        with (run.folder / "run.log").open("a", encoding="utf-8") as log:
            log.write(f"{time.strftime('%H:%M:%S')} {level:<7} {message}\n")
        number = logging.getLevelName(level)
        _RUN_LOGGER.log(
            number if isinstance(number, int) else logging.INFO, "%s", message
        )
        self.bridge.emit_event(
            "run.log", {"run_id": run.id, "level": level, "message": message}
        )

    def _process_finished(self, run: Run, exit_code: int) -> None:
        if run.status in FINAL_STATES:
            return
        if run.kill_requested:
            self._finish(
                run, "killed", error="The run did not stop in time: it was killed."
            )
        else:
            self._finish(
                run,
                "failed",
                error=f"The runner stopped unexpectedly (exit code {exit_code}).",
            )

    def _process_error(self, run: Run, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._finish(
                run,
                "failed",
                error=(
                    "The runner could not be started: check the Python "
                    "interpreter in the preferences."
                ),
            )

    def _finish(self, run: Run, status: str, error: str | None = None) -> None:
        if run.status in FINAL_STATES:
            return
        run.status = status
        run.error = error
        run.finished = datetime.now().isoformat(timespec="seconds")
        if run.stop_timer is not None:
            run.stop_timer.stop()
        self._unlock(run)
        self._save(run)
        if error:
            _RUN_LOGGER.error("Run %s %s: %s", run.id, status, error)
        else:
            _RUN_LOGGER.info("Run %s %s", run.id, status)
        self.bridge.emit_event("run.finished", run.to_dict())
        self.bridge.emit_event("runs.changed", None)

    # Stop ----------------------------------------------------------------------

    def stop(self, run_id: str) -> None:
        """Ask a run to stop; kill it if it does not stop in time."""
        run = self.runs.get(run_id)
        if run is None or run.status in FINAL_STATES:
            return
        if run.process is None:  # Still in its dry run.
            self._finish(run, "stopped")
            return
        _RUN_LOGGER.info("Stopping run %s", run.id)
        run.process.write((encode({"command": "stop"}) + "\n").encode("utf-8"))
        run.stop_timer = QTimer(self)
        run.stop_timer.setSingleShot(True)
        run.stop_timer.timeout.connect(lambda: self.kill(run.id))
        run.stop_timer.start(int(self.preferences.preferences.stop_timeout_s * 1000))

    def kill(self, run_id: str) -> None:
        """Kill a run and its child processes."""
        run = self.runs.get(run_id)
        if run is None or run.process is None or run.status in FINAL_STATES:
            return
        run.kill_requested = True
        pid = run.process.processId()
        if pid:
            kill_tree(pid)
        run.process.waitForFinished(3000)
        self._process_finished(run, -1)

    def stop_all(self) -> None:
        """Kill every active run (when the application closes)."""
        for run in self.active():
            self.kill(run.id)

    # Folder and lock -----------------------------------------------------------

    def _save(self, run: Run) -> None:
        info = run.to_info()
        write_info(run.folder, info)
        self.run_changed.emit(run.id)
        self.bridge.emit_event("run.updated", info.model_dump(mode="json"))

    def _lock(self, run: Run) -> None:
        target = self.session.project.find(run.target)
        if not isinstance(target, ContainerNode):
            return
        reason = f"{run.target_name} is running: stop the run before changing it."
        run.locked = [node.id for node, _ in iter_nodes(target)]
        for node_id in run.locked:
            self.session.document.locked[node_id] = reason

    def _unlock(self, run: Run) -> None:
        for node_id in run.locked:
            self.session.document.locked.pop(node_id, None)
        run.locked = []
