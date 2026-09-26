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
from gemseo_process_builder.core.model import NodeLayout
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.script_project import backup_file
from gemseo_process_builder.core.script_project import side_file
from gemseo_process_builder.core.serialization import project_to_data


class Scripts:
    """Records the scripts to read in the worker."""

    def __init__(self) -> None:
        self.started: list[Path] = []

    def start(self, path: Path) -> None:
        self.started.append(path)


def controller(tmp_path: Path) -> ProjectController:
    session = ProjectSession(tmp_path / "untitled.gpb.json.autosave")
    bridge = Bridge(MethodRegistry())
    bridge.emit_event = lambda name, payload: None  # type: ignore[method-assign]
    preferences = PreferencesStore(tmp_path / "preferences.json")
    projects = ProjectController(session, bridge, UnattendedDialogs(), preferences)
    scripts: Any = Scripts()
    projects.scripts = scripts
    return projects


def test_a_project_saved_as_a_script_opens_as_it_was(tmp_path: Path) -> None:
    projects = controller(tmp_path)
    session = projects.session
    session.project = example("sellar_mdf")
    session.project.layout.nodes["n-sellar1"] = NodeLayout(x=321.0, y=12.0)
    script = tmp_path / "sellar.py"
    session.save(script)
    text = script.read_text("utf-8")
    assert "def build_scenario() -> MDOScenario:" in text
    assert "Run it with: python sellar.py" in text
    assert side_file(script).is_file()
    assert session.save_notes == []
    saved = project_to_data(session.project, tmp_path)
    projects.session.new()
    assert projects.open(OpenParams(path=str(script))) == {"cancelled": False}
    assert project_to_data(projects.session.project, tmp_path) == saved
    assert projects.session.path == script.resolve()
    assert projects.scripts.started == []  # Not read again: it did not change.


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


def test_a_script_changed_since_it_was_saved_is_read_again(tmp_path: Path) -> None:
    projects = controller(tmp_path)
    projects.session.project = example("sellar_mdf")
    script = tmp_path / "sellar.py"
    projects.session.save(script)
    script.write_text(script.read_text("utf-8") + "\n# Changed by hand.\n", "utf-8")
    result = projects.open(OpenParams(path=str(script)))
    assert result == {"cancelled": False, "reading": True}
    assert projects.scripts.started == [script]
    # Its side file gives the layout back once read.
    read = example("sellar_mdf").model_dump(mode="json")
    for node in read["root"]["children"][0]["children"]:
        node["id"] = f"n-read-{node['name']}"
    projects._script_read(
        script, {"ok": True, "result": {"project": read, "warnings": []}}
    )
    ids = [child.id for child in projects.session.project.root.children[0].children]
    assert ids == ["n-sellar1", "n-sellar2", "n-sellarsystem"]
    assert projects.session.path == script.resolve()


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


def test_a_project_not_complete_yet_is_kept_next_to_its_script(tmp_path: Path) -> None:
    projects = controller(tmp_path)
    session = projects.session
    session.project = Project()  # An empty model: no script yet.
    script = tmp_path / "draft.py"
    session.save(script)
    assert script.read_text("utf-8") == '"""draft: not complete yet."""\n'
    assert "not written yet" in session.save_notes[0]
    session.new()
    assert projects.open(OpenParams(path=str(script))) == {"cancelled": False}
