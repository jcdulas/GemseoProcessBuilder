"""Projects saved and opened as GEMSEO scripts, in the UI process."""

from pathlib import Path
from typing import Any

from golden_projects import example

from gemseo_process_builder.app.api_project import OpenParams
from gemseo_process_builder.app.api_project import ProjectController
from gemseo_process_builder.app.benchmark_mode import UnattendedDialogs
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.preferences import PreferencesStore
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.model import RunRef
from gemseo_process_builder.core.model import SurrogateRef
from gemseo_process_builder.core.script_project import backup_file
from gemseo_process_builder.core.serialization import save_project
from gemseo_process_builder.results.models import RunInfo
from gemseo_process_builder.results.models import write_info
from gemseo_process_builder.results.surrogates import SourceRun
from gemseo_process_builder.results.surrogates import SurrogateMetadata
from gemseo_process_builder.results.surrogates import SurrogateVariable
from gemseo_process_builder.results.surrogates import write_metadata


class Scripts:
    """Records the scripts to read in the worker."""

    def __init__(self) -> None:
        self.started: list[Path] = []

    def start(self, path: Path) -> None:
        self.started.append(path)


class Dialogs(UnattendedDialogs):
    """Saves where told, and recovers autosaves."""

    def __init__(self) -> None:
        self.save_to: Path | None = None

    def ask_save_project(self, suggested_name: str) -> Path | None:
        return self.save_to

    def ask_recover(self, project_name: str) -> bool:
        return True


def controller(tmp_path: Path) -> ProjectController:
    session = ProjectSession(tmp_path / "data" / "untitled.gpb.json.autosave")
    bridge = Bridge(MethodRegistry())
    bridge.emit_event = lambda name, payload: None  # type: ignore[method-assign]
    preferences = PreferencesStore(tmp_path / "preferences.json")
    projects = ProjectController(session, bridge, Dialogs(), preferences)
    scripts: Any = Scripts()
    projects.scripts = scripts
    return projects


def read(projects: ProjectController, script: Path, project: Project) -> None:
    """Give the controller the project the worker read from a script."""
    result = {"project": project.model_dump(mode="json"), "warnings": []}
    projects._script_read(script, {"ok": True, "result": result})


def test_saving_writes_the_script_only(tmp_path: Path) -> None:
    session = controller(tmp_path).session
    session.project = example("sellar_mdf")
    script = tmp_path / "sellar.py"
    session.save(script)
    text = script.read_text("utf-8")
    assert text.startswith('"""Sellar MDF.\n')
    assert "def build_scenario() -> MDOScenario:" in text
    assert "Run it with: python sellar.py" in text
    assert session.save_notes == []
    assert not session.dirty
    # Its lock is in the data of the application, not next to it.
    assert (session.storage / "lock").is_file()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["data", "sellar.py"]
    storage = session.storage
    session.release_lock()
    assert not storage.exists()  # Nothing left in it.


def test_opening_a_script_reads_it(tmp_path: Path) -> None:
    projects = controller(tmp_path)
    script = tmp_path / "sellar.py"
    script.write_text('"""Sellar MDF."""\n', "utf-8")
    result = projects.open(OpenParams(path=str(script)))
    assert result == {"cancelled": False, "reading": True}
    assert projects.scripts.started == [script]
    read(projects, script, example("sellar_mdf"))
    assert projects.session.path == script.resolve()
    assert not projects.session.dirty
    assert projects.session.name == "Sellar MDF"


def test_the_runs_and_surrogates_of_older_projects_are_moved_and_found(
    tmp_path: Path,
) -> None:
    projects = controller(tmp_path)
    script = tmp_path / "sellar.py"
    run = tmp_path / "Sellar MDF.runs" / "r-1"
    run.mkdir(parents=True)
    info = RunInfo(
        id="r-1",
        driver="n-an-old-id",
        driver_name="Optimizer",
        driver_path="Model.Optimizer",
        created="2026-09-26T10:00:00",
    )
    write_info(run, info)
    model = tmp_path / "Sellar MDF.surrogates" / "Sellar_RBF.pkl"
    model.parent.mkdir()
    model.write_bytes(b"pickle")
    metadata = SurrogateMetadata(
        id="s-1",
        name="Sellar RBF",
        algorithm="RBFRegressor",
        source=SourceRun(id="r-1"),
        inputs=[SurrogateVariable(name="x_1")],
        outputs=[SurrogateVariable(name="obj")],
        n_samples=30,
        n_folds=5,
        created="2026-09-26T10:00:00",
        updated="2026-09-26T10:00:00",
    )
    write_metadata(model, metadata)
    read(projects, script, example("sellar_mdf"))
    session = projects.session
    project = session.project
    assert [(ref.id, ref.driver) for ref in project.runs] == [("r-1", "n-optimizer")]
    assert project.runs[0].run_path == str(session.storage / "runs" / "r-1")
    assert [(ref.id, ref.name) for ref in project.surrogates] == [("s-1", "Sellar RBF")]
    assert (session.storage / "surrogates" / "Sellar_RBF.json").is_file()
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "data",
        "preferences.json",
    ]


def test_save_as_takes_the_runs_and_surrogates_along(tmp_path: Path) -> None:
    session = controller(tmp_path).session
    session.project = example("rosenbrock_surrogate")
    first = tmp_path / "first.py"
    session.save(first)
    run = session.storage / "runs" / "r-1"
    run.mkdir(parents=True)
    session.project.runs.append(RunRef(id="r-1", driver="n-doe", run_path=str(run)))
    model = session.storage / "surrogates" / "Rosenbrock.pkl"
    model.parent.mkdir()
    model.write_bytes(b"pickle")
    session.project.surrogates.append(
        SurrogateRef(id="s-1", name="Rosenbrock", model_path=str(model))
    )
    surrogate = session.project.find("n-surrogate")
    assert isinstance(surrogate, ComponentNode)
    surrogate.config["model_path"] = str(model)
    old = session.storage
    session.save(tmp_path / "second.py")
    new = session.storage
    assert new != old
    assert session.project.runs[0].run_path == str(new / "runs" / "r-1")
    assert (new / "runs" / "r-1").is_dir()
    assert session.project.surrogates[0].model_path == str(
        new / "surrogates" / "Rosenbrock.pkl"
    )
    assert surrogate.config["model_path"] == session.project.surrogates[0].model_path
    assert session.data_moved
    assert not old.exists()


def test_saving_again_keeps_the_code_of_the_user(tmp_path: Path) -> None:
    session = controller(tmp_path).session
    session.project = example("sellar_mdf")
    script = tmp_path / "sellar.py"
    session.save(script)
    edited = script.read_text("utf-8").replace(
        'if __name__ == "__main__":',
        'def report():\n    return "done"\n\n\nif __name__ == "__main__":',
    )
    script.write_text(edited, "utf-8")
    session.save()
    assert 'def report():\n    return "done"' in script.read_text("utf-8")
    assert session.save_notes == ["Kept from your script: report."]


def test_the_first_save_of_a_script_written_by_hand_keeps_its_original(
    tmp_path: Path,
) -> None:
    session = controller(tmp_path).session
    script = tmp_path / "study.py"
    original = (
        "from gemseo import create_scenario\n\n\n"
        "def helper():\n    return 1\n\n\n"
        "scenario = create_scenario([], 'obj', None)\n"
    )
    script.write_text(original, "utf-8")
    session.adopt(example("sellar_mdf"), script=script)
    session.save()
    assert backup_file(script).read_text("utf-8") == original
    text = script.read_text("utf-8")
    assert "def helper():" in text
    assert "scenario = create_scenario([], 'obj', None)" not in text
    assert session.save_notes[0].startswith("The study of study.py is now written")


def test_a_project_not_complete_yet_stays_in_its_autosave(tmp_path: Path) -> None:
    projects = controller(tmp_path)
    session = projects.session
    session.project = Project()  # An empty model: no script yet.
    session.project.metadata.name = "Draft"
    script = tmp_path / "draft.py"
    session.save(script)
    assert script.read_text("utf-8") == '"""Draft: not complete yet."""\n'
    assert "is not written yet" in session.save_notes[0]
    assert session.dirty
    assert session.autosave_of(script).is_file()
    # Opened again: recovered from the autosave, not read.
    session.release_lock()
    session.dirty = False
    assert projects.open(OpenParams(path=str(script))) == {"cancelled": False}
    assert projects.scripts.started == []
    assert session.name == "Draft"
    assert session.path == script.resolve()


def test_a_project_of_an_older_version_is_saved_as_a_script(tmp_path: Path) -> None:
    projects = controller(tmp_path)
    older = tmp_path / "sellar.gpb.json"
    save_project(example("sellar_mdf"), older)
    assert projects.open(OpenParams(path=str(older))) == {"cancelled": False}
    assert projects.session.name == "Sellar MDF"
    script = tmp_path / "sellar.py"
    projects.dialogs.save_to = script  # type: ignore[attr-defined]
    assert projects.save()["saved"] is True
    assert projects.session.path == script.resolve()
    assert "def build_scenario()" in script.read_text("utf-8")


def test_a_moved_script_finds_its_runs_again(tmp_path: Path) -> None:
    projects = controller(tmp_path)
    events: list[tuple[str, Any]] = []
    projects.bridge.emit_event = lambda name, payload: events.append((name, payload))  # type: ignore[method-assign]
    session = projects.session
    session.project = example("sellar_mdf")
    script = tmp_path / "work" / "sellar.py"
    script.parent.mkdir()
    session.save(script)
    storage = session.storage
    run = storage / "runs" / "r-1"
    run.mkdir(parents=True)
    info = RunInfo(
        id="r-1",
        driver="n-optimizer",
        driver_name="Optimizer",
        driver_path="Model.Optimizer",
        created="2026-09-26T10:00:00",
    )
    write_info(run, info)
    session.new()
    moved = tmp_path / "elsewhere" / "sellar.py"
    moved.parent.mkdir()
    script.rename(moved)
    read(projects, moved, example("sellar_mdf"))
    assert session.storage == storage
    assert [ref.id for ref in session.project.runs] == ["r-1"]
    (read_event,) = [
        payload for name, payload in events if name == "project.scriptRead"
    ]
    assert "were found again" in read_event["warnings"][0]
    # Its folder now follows the new place of the script.
    assert session.storage_of(moved) == storage
