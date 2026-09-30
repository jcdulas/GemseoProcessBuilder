"""The copilot for the page: the journal of a run, the environment of the runner."""

import json
import os
import sys
from pathlib import Path

import pytest

from gemseo_process_builder.app.api_copilot import read_journal
from gemseo_process_builder.app.api_copilot import run_session
from gemseo_process_builder.app.api_copilot import session_command
from gemseo_process_builder.app.api_copilot import session_environment
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.preferences import Preferences
from gemseo_process_builder.app.run_manager import copilot_environment
from gemseo_process_builder.app.worker_client import PACKAGE_PARENT


class Store:
    def __init__(self, folders: dict[str, Path]) -> None:
        self.folders = folders

    def folder_of(self, run_id: str) -> Path | None:
        return self.folders.get(run_id)


def test_the_journal_of_a_run(tmp_path: Path) -> None:
    journal = tmp_path / "copilot" / "journal.jsonl"
    journal.parent.mkdir()
    records = [
        {"kind": "call", "trigger": "start", "context": "{...}"},
        {"kind": "answer", "text": "Fine."},
    ]
    lines = [json.dumps(record) for record in records]
    journal.write_text("\n".join(lines) + '\n{"kind": "cut', encoding="utf-8")
    store = Store({"r-1": tmp_path, "r-2": tmp_path / "other"})
    assert read_journal(store, "r-1") == [  # type: ignore[arg-type]
        {"kind": "call", "trigger": "start"},
        {"kind": "answer", "text": "Fine."},
    ]
    assert read_journal(store, "r-2") == []  # type: ignore[arg-type]
    with pytest.raises(BridgeError, match="There is no run r-3"):
        read_journal(store, "r-3")  # type: ignore[arg-type]


def test_the_runner_gets_the_choices_of_the_user() -> None:
    preferences = Preferences(
        copilot_backend="api_key", copilot_decision_model="claude-opus-5"
    )
    assert copilot_environment(preferences) == {
        "GEMSEO_CLAUDE_PILOT_BACKEND": "api_key",
        "GEMSEO_CLAUDE_PILOT_WATCH_MODEL": "claude-opus-5-5",
        "GEMSEO_CLAUDE_PILOT_DECISION_MODEL": "claude-opus-5",
        "GEMSEO_CLAUDE_PILOT_EFFORT": "low",
    }


FAKE_SESSION = (
    "import json, sys; request = json.load(sys.stdin); print('printed by user code');"
    " ok = request['question'] != 'fail';"
    " answer = {'ok': ok, 'text': request['question'], 'error': 'No backend.'};"
    " print(json.dumps(answer))"
)


def test_the_copilot_process_answers(tmp_path: Path) -> None:
    command = [sys.executable, "-c", FAKE_SESSION]
    answer = run_session({"question": "Why?"}, command, dict(os.environ), tmp_path)
    assert answer == {"ok": True, "text": "Why?", "error": "No backend."}


def test_the_copilot_process_cannot_answer(tmp_path: Path) -> None:
    command = [sys.executable, "-c", FAKE_SESSION]
    with pytest.raises(BridgeError, match="No backend") as refused:
        run_session({"question": "fail"}, command, dict(os.environ), tmp_path)
    assert refused.value.code == "conflict"


def test_a_copilot_process_that_cannot_start(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "import sys; sys.exit('No module named x')"]
    with pytest.raises(BridgeError, match="could not start: No module named x"):
        run_session({}, command, dict(os.environ), tmp_path)


def test_the_copilot_process_runs_as_the_runs() -> None:
    preferences = Preferences(python_interpreter="C:/envs/gemseo/python.exe")
    assert session_command(preferences) == [
        "C:/envs/gemseo/python.exe",
        "-m",
        "gemseo_claude_pilot.session",
    ]
    environment = session_environment(preferences)
    assert environment["GEMSEO_CLAUDE_PILOT_BACKEND"] == "claude_code"
    assert PACKAGE_PARENT in environment["PYTHONPATH"].split(os.pathsep)
