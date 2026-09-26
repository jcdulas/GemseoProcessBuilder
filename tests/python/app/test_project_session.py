import inspect
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from golden_projects import example

from gemseo_process_builder.app.api_project import OpenParams
from gemseo_process_builder.app.api_project import ProjectController
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.dialogs import UnsavedChoice
from gemseo_process_builder.app.preferences import PreferencesStore
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.app.project_session import recovery_candidate
from gemseo_process_builder.core.model import Project


class FakeDialogs:
    def __init__(self) -> None:
        self.open_path: Path | None = None
        self.save_path: Path | None = None
        self.unsaved: UnsavedChoice = "discard"
        self.recover = True
        self.questions: list[str] = []
        self.errors: list[str] = []

    def ask_open_project(self) -> Path | None:
        self.questions.append("open")
        return self.open_path

    def ask_save_project(self, suggested_name: str) -> Path | None:
        self.questions.append(f"save {suggested_name}")
        return self.save_path

    def ask_unsaved_changes(self, project_name: str) -> UnsavedChoice:
        self.questions.append(f"unsaved {project_name}")
        return self.unsaved

    def ask_recover(self, project_name: str) -> bool:
        self.questions.append(f"recover {project_name}")
        return self.recover

    def show_error(self, title: str, message: str) -> None:
        self.errors.append(message)


def untitled_study() -> Project:
    """A study that can be saved as a script, not named yet."""
    project = example("sellar_mdf")
    project.metadata.name = "Untitled"
    return project


@pytest.fixture
def session(tmp_path: Path) -> ProjectSession:
    session = ProjectSession(tmp_path / "data" / "untitled.gpb.json.autosave")
    session.project = untitled_study()
    return session


@pytest.fixture
def dialogs() -> FakeDialogs:
    return FakeDialogs()


@pytest.fixture
def controller(
    session: ProjectSession, dialogs: FakeDialogs, tmp_path: Path
) -> ProjectController:
    return ProjectController(
        session,
        Bridge(MethodRegistry()),
        dialogs,
        PreferencesStore(tmp_path / "prefs.json"),
    )


def modify(session: ProjectSession) -> None:
    session.project.metadata.description = "Changed"
    session.set_dirty()


def test_dirty_flag_and_notifications(session: ProjectSession) -> None:
    changes: list[bool] = []
    session.on_change(lambda: changes.append(session.dirty))
    session.set_dirty()
    session.set_dirty()
    session.set_dirty(False)
    assert changes == [True, True, False]


def test_first_save_names_the_project(session: ProjectSession, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no script yet"):
        session.save()
    path = session.save(tmp_path / "Wing.py")
    assert session.name == "Wing"
    assert session.path == path
    assert not session.dirty


def test_autosave_only_when_dirty(session: ProjectSession, tmp_path: Path) -> None:
    session.save(tmp_path / "p.py")
    assert not session.write_autosave()
    modify(session)
    assert session.write_autosave()
    assert session.autosave_of(tmp_path / "p.py").exists()
    session.save()
    assert not session.autosave_of(tmp_path / "p.py").exists()


def test_untitled_autosave(session: ProjectSession) -> None:
    modify(session)
    session.write_autosave()
    assert session.untitled_autosave.exists()
    other = ProjectSession(session.untitled_autosave)
    other.recover_untitled()
    assert other.project.metadata.description == "Changed"
    assert other.dirty


def test_recovery_candidate_uses_modification_times(tmp_path: Path) -> None:
    project = tmp_path / "p.py"
    project.write_text("{}")
    autosave = tmp_path / "autosave.json"
    assert recovery_candidate(project, autosave) is None
    autosave.write_text("{}")
    past = time.time() - 60
    os.utime(project, (past, past))
    assert recovery_candidate(project, autosave) == autosave
    os.utime(autosave, (past - 60, past - 60))
    assert recovery_candidate(project, autosave) is None


def test_open_recovers_a_newer_autosave(
    controller: ProjectController, session: ProjectSession, tmp_path: Path
) -> None:
    # A previous session saved "p", changed it, autosaved and crashed.
    path = tmp_path / "p.py"
    crashed = ProjectSession(session.untitled_autosave)  # Same user data.
    crashed.project = untitled_study()
    crashed.save(path)
    modify(crashed)
    crashed.write_autosave()
    past = time.time() - 60
    os.utime(path, (past, past))

    assert controller.open(OpenParams(path=str(path))) == {"cancelled": False}
    assert session.dirty
    assert session.project.metadata.description == "Changed"


def test_open_discards_the_autosave_if_refused(
    controller: ProjectController,
    session: ProjectSession,
    dialogs: FakeDialogs,
    tmp_path: Path,
) -> None:
    path = tmp_path / "p.py"
    session.save(path)
    session.autosave_of(path).write_text("{}")
    past = time.time() - 60
    os.utime(path, (past, past))
    dialogs.recover = False
    reading: list[Path] = []
    controller.scripts = SimpleNamespace(start=reading.append)  # type: ignore[assignment]
    assert controller.open(OpenParams(path=str(path)))["reading"]
    assert reading == [path]  # The script is read instead.
    assert not session.autosave_of(path).exists()


def test_unsaved_changes_can_cancel_new(
    controller: ProjectController, session: ProjectSession, dialogs: FakeDialogs
) -> None:
    modify(session)
    dialogs.unsaved = "cancel"
    assert controller.new() == {"cancelled": True}
    assert session.project.root.children


def test_unsaved_changes_can_be_saved_first(
    controller: ProjectController,
    session: ProjectSession,
    dialogs: FakeDialogs,
    tmp_path: Path,
) -> None:
    modify(session)
    dialogs.unsaved = "save"
    dialogs.save_path = tmp_path / "Saved.py"
    controller.new()
    assert (tmp_path / "Saved.py").exists()
    assert not session.project.root.children
    assert controller.recent() == [str((tmp_path / "Saved.py").resolve())]


def test_open_dialog_cancelled(
    controller: ProjectController, dialogs: FakeDialogs
) -> None:
    assert controller.open(OpenParams()) == {"cancelled": True}
    assert dialogs.questions == ["open"]


def test_invalid_file_is_reported(
    controller: ProjectController, tmp_path: Path
) -> None:
    path = tmp_path / "bad.gpb.json"
    path.write_text("nonsense")
    with pytest.raises(BridgeError) as error:
        controller.open(OpenParams(path=str(path)))
    assert error.value.code == "invalid_file"


def test_open_recent_shows_errors(
    controller: ProjectController, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    controller.open_recent(str(tmp_path / "missing.gpb.json"))
    assert "Cannot read" in dialogs.errors[0]


def test_confirm_close_removes_the_autosave(
    controller: ProjectController, session: ProjectSession
) -> None:
    modify(session)
    session.write_autosave()
    assert controller.confirm_close()
    assert not session.untitled_autosave.exists()


def test_startup_recovery(
    controller: ProjectController, session: ProjectSession, dialogs: FakeDialogs
) -> None:
    modify(session)
    session.write_autosave()
    session.project.metadata.description = ""
    controller.recover_untitled_at_startup()
    assert session.project.metadata.description == "Changed"
    assert dialogs.questions == ["recover The untitled project"]


def test_the_window_title_takes_the_whole_state(session: ProjectSession) -> None:
    # The window shows the state of the session: every key of it.
    from gemseo_process_builder.app.main_window import MainWindow

    inspect.signature(MainWindow.show_project).bind(None, **session.state())
