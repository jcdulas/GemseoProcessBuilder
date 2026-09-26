import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from builders import component
from builders import driver
from builders import project
from PySide6.QtCore import QCoreApplication
from PySide6.QtCore import QEventLoop

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.preferences import PreferencesStore
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.app.run_manager import FINAL_STATES
from gemseo_process_builder.app.run_manager import Run
from gemseo_process_builder.app.run_manager import RunError
from gemseo_process_builder.app.run_manager import RunManager
from gemseo_process_builder.app.run_manager import new_run_id
from gemseo_process_builder.core.commands import CommandError
from gemseo_process_builder.core.commands import SetDriverConfig
from gemseo_process_builder.core.validation import Problem

FAKE_RUNNER = Path(__file__).with_name("fake_runner.py")


class FakeWorker:
    """Answers the dry run at once."""

    def __init__(self) -> None:
        self.issues: list[dict[str, Any]] = []

    def request(self, method: str, params: Any, callback: Any, timeout: float) -> str:
        callback({"id": "1", "ok": True, "result": self.issues})
        return "1"


class Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.session = ProjectSession(tmp_path / "untitled.gpb.json.autosave")
        model = component("Model", ["x"], ["y"], config={"expressions": {"y": "2*x"}})
        self.session.project = project(driver("Study", "mda", model))
        self.events: list[tuple[str, Any]] = []
        bridge = Bridge(MethodRegistry())
        bridge.emit_event = lambda name, payload: self.events.append((name, payload))  # type: ignore[method-assign]
        self.preferences = PreferencesStore(tmp_path / "preferences.json")
        self.preferences.preferences.stop_timeout_s = 0.3
        self.problems: list[Problem] = []
        self.worker = FakeWorker()
        self.runs = RunManager(
            self.session,
            bridge,
            self.worker,  # type: ignore[arg-type]
            self.preferences,
            lambda: self.problems,
        )

    def start(self, mode: str) -> Run:
        self.runs.runner_command = [sys.executable, str(FAKE_RUNNER), mode]
        return self.runs.start("n-Study")

    def wait(self, run: Run, status: str = "", timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            if run.status == status or (not status and run.status in FINAL_STATES):
                return
        pytest.fail(f"The run is still {run.status}.")


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def run_json(run: Run) -> dict[str, Any]:
    return json.loads((run.folder / "run.json").read_text(encoding="utf-8"))


def test_completed_run(harness: Harness) -> None:
    run = harness.start("complete")
    # In the data of the application, hidden from the user.
    assert run.folder.parent == harness.session.storage / "runs"
    assert {path.name for path in run.folder.iterdir()} >= {
        "project.gpb.json",
        "script.py",
        "script.gpb-map.json",
        "run.json",
    }
    harness.wait(run)
    saved = run_json(run)
    assert saved["status"] == "completed"
    assert saved["summary"]["best_objective"] == 1.0
    assert saved["variables"][0]["role"] == "design variable"
    assert saved["versions"]["python"] == "3.12"
    assert saved["driver_path"] == "Model.Study"
    assert saved["duration_s"] is not None
    (ref,) = harness.session.project.runs
    assert (ref.id, ref.run_path) == (run.id, str(run.folder))
    assert "Hello from the run." in (run.folder / "run.log").read_text(encoding="utf-8")
    names = [name for name, _ in harness.events]
    assert names.index("run.started") < names.index("run.log")
    assert "run.log" in names
    assert (
        "run.event",
        {"run_id": run.id, "event": "iteration", "payload": {"index": 1}},
    ) in harness.events
    assert names[-2:] == ["run.finished", "runs.changed"]


def test_stop(harness: Harness) -> None:
    run = harness.start("stop")
    harness.wait(run, "running")
    harness.runs.stop(run.id)
    harness.wait(run)
    assert run_json(run)["status"] == "stopped"


def test_a_run_that_does_not_stop_is_killed(harness: Harness) -> None:
    run = harness.start("hang")
    harness.wait(run, "running")
    harness.runs.stop(run.id)
    harness.wait(run)
    assert run_json(run)["status"] == "killed"


def test_a_crashed_runner_fails_the_run(harness: Harness) -> None:
    run = harness.start("crash")
    harness.wait(run)
    assert run.status == "failed"
    assert "exit code 3" in str(run.error)


def test_a_failed_dry_run_does_not_start_the_runner(harness: Harness) -> None:
    harness.worker.issues = [{"node": "n-Model", "message": "TypeError: no", "line": 3}]
    run = harness.start("complete")
    assert run.status == "failed"
    assert run.error == "The dry run failed: TypeError: no"
    assert run.process is None


def test_the_running_driver_cannot_be_edited(harness: Harness) -> None:
    run = harness.start("stop")
    harness.wait(run, "running")
    with pytest.raises(CommandError, match="Study is running"):
        harness.session.document.execute(
            SetDriverConfig(id="n-Study", field="mda_settings", value={"tolerance": 1})
        )
    assert harness.session.project.find("n-Study").config == {}  # type: ignore[union-attr]
    harness.runs.stop(run.id)
    harness.wait(run)
    harness.session.document.execute(
        SetDriverConfig(id="n-Study", field="mda_settings", value={"tolerance": 1})
    )


def test_runs_are_refused(harness: Harness) -> None:
    harness.problems = [Problem("x", "error", "Broken.", "n-Model")]
    with pytest.raises(RunError, match="Fix the 1 errors"):
        harness.start("complete")
    harness.problems = []
    run = harness.start("stop")
    with pytest.raises(RunError, match="A run is in progress"):
        harness.start("complete")
    harness.runs.stop(run.id)
    harness.wait(run)


def test_run_ids_are_unique(tmp_path: Path) -> None:
    now = datetime(2026, 9, 24, 10, 15, 0)
    (tmp_path / "r-20260924-101500").mkdir()
    assert new_run_id(tmp_path, now) == "r-20260924-101500-2"
