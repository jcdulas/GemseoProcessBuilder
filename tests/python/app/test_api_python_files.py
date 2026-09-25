"""Creating and editing the Python file of a discipline class from the inspector."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from builders import component
from builders import project

from gemseo_process_builder.app.api_python_files import CreateParams
from gemseo_process_builder.app.api_python_files import NodeParams
from gemseo_process_builder.app.api_python_files import PythonFileService
from gemseo_process_builder.app.api_python_files import VariableModel
from gemseo_process_builder.app.api_python_files import VariablesParams
from gemseo_process_builder.app.api_python_files import editor_command
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.project_session import ProjectSession

VARIABLES = [
    VariableModel(name="span", direction="in", default=[10.0]),
    VariableModel(name="area", direction="out"),
]


class Components:
    """Records the components asked to read their ports again."""

    def __init__(self) -> None:
        self.introspected: list[str] = []

    def introspect(self, node_id: str) -> None:
        self.introspected.append(node_id)


@pytest.fixture
def service(tmp_path: Path) -> PythonFileService:
    session = ProjectSession(tmp_path / "untitled.gpb.json.autosave")
    session.project = project(component("Wing", kind="python_class"))
    components: Any = Components()
    preferences: Any = SimpleNamespace(preferences=SimpleNamespace(code_editor=""))
    return PythonFileService(session, Bridge(MethodRegistry()), components, preferences)


def test_creating_a_file_points_the_component_to_its_class(
    service: PythonFileService, tmp_path: Path
) -> None:
    path = tmp_path / "wing"
    result = service.create(
        CreateParams(
            id="n-Wing", path=str(path), class_name="Wing", variables=VARIABLES
        )
    )
    assert result == {"path": str(tmp_path / "wing.py")}
    assert "class Wing(Discipline):" in (tmp_path / "wing.py").read_text("utf-8")
    node = service.session.project.find("n-Wing")
    assert node.config == {
        "module_path": str(tmp_path / "wing.py"),
        "init_args": {},
        "class": "Wing",
    }
    # One undo step; an existing file is never replaced.
    service.session.document.undo()
    assert service.session.project.find("n-Wing").config == {}
    with pytest.raises(BridgeError, match="already exists"):
        service.create(
            CreateParams(
                id="n-Wing", path=str(path), class_name="Wing", variables=VARIABLES
            )
        )


def test_editing_the_variables_rewrites_the_class(
    service: PythonFileService, tmp_path: Path
) -> None:
    path = tmp_path / "wing.py"
    service.create(
        CreateParams(
            id="n-Wing", path=str(path), class_name="Wing", variables=VARIABLES
        )
    )
    read = service.variables(NodeParams(id="n-Wing"))
    assert (read["managed"], read["error"]) == (True, "")
    assert read["variables"][0] == {
        "name": "span",
        "direction": "in",
        "default": [10.0],
    }
    added = [
        *VARIABLES,
        VariableModel(name="chord", direction="in", default=[1.0, 2.0]),
    ]
    written = service.set_variables(VariablesParams(id="n-Wing", variables=added))
    assert [v["name"] for v in written["variables"]] == ["span", "chord", "area"]
    assert service.components.introspected == ["n-Wing"]
    with pytest.raises(BridgeError, match="at least one output"):
        service.set_variables(VariablesParams(id="n-Wing", variables=added[:1]))


def test_a_class_written_by_hand_is_read_only(
    service: PythonFileService, tmp_path: Path
) -> None:
    path = tmp_path / "mine.py"
    path.write_text("class Mine:\n    pass\n", encoding="utf-8")
    service.session.project.find("n-Wing").config.update(
        module_path=str(path), **{"class": "Mine"}
    )
    assert service.variables(NodeParams(id="n-Wing"))["managed"] is False
    with pytest.raises(BridgeError, match="edit them in the code"):
        service.set_variables(VariablesParams(id="n-Wing", variables=VARIABLES))


def test_the_editor_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = Path("C:/work/wing.py")
    assert editor_command("code -w", path) == ["code", "-w", str(path)]
    assert editor_command('myedit --open "{file}" --line 1', path)[2] == str(path)
    monkeypatch.setattr("shutil.which", lambda name: "/bin/code")
    assert editor_command("", path) == ["/bin/code", str(path)]
    # Named vscode on some machines.
    monkeypatch.setattr(
        "shutil.which", lambda name: "/bin/vscode" if name == "vscode" else None
    )
    assert editor_command("", path) == ["/bin/vscode", str(path)]
    # Installed but not on the path (Windows).
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    assert editor_command("", path)[0] == "notepad.exe"
    exe = tmp_path / "Programs" / "Microsoft VS Code" / "Code.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert editor_command("", path) == [str(exe), str(path)]
    exe.unlink()
    assert editor_command("", path)[-1] == str(path)
    assert editor_command("", path)[0] != "python"


def test_a_file_saved_in_the_editor_updates_its_components(
    service: PythonFileService, tmp_path: Path
) -> None:
    path = tmp_path / "wing.py"
    service.create(
        CreateParams(
            id="n-Wing", path=str(path), class_name="Wing", variables=VARIABLES
        )
    )
    events: list[tuple[str, Any]] = []
    service.bridge.emit_event = lambda name, payload: events.append((name, payload))  # type: ignore[method-assign]
    service._file_changed(str(path))
    service._reload()
    assert service.components.introspected == ["n-Wing"]
    assert events == [
        ("pythonFile.changed", {"path": events[0][1]["path"], "nodes": ["n-Wing"]})
    ]
