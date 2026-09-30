"""The demos of the Library: listed, and opened as copies."""

from pathlib import Path
from typing import Any

import pytest

from gemseo_process_builder.app.api_demos import DemoParams
from gemseo_process_builder.app.api_demos import DemoService
from gemseo_process_builder.app.api_project import ProjectController
from gemseo_process_builder.app.benchmark_mode import UnattendedDialogs
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.preferences import PreferencesStore
from gemseo_process_builder.app.project_session import ProjectSession


class Scripts:
    """Records the scripts to read in the worker."""

    def __init__(self) -> None:
        self.started: list[Path] = []

    def start(self, path: Path) -> None:
        self.started.append(path)


def service(tmp_path: Path) -> DemoService:
    session = ProjectSession(tmp_path / "data" / "untitled.gpb.json.autosave")
    bridge = Bridge(MethodRegistry())
    bridge.emit_event = lambda name, payload: None  # type: ignore[method-assign]
    projects = ProjectController(
        session, bridge, UnattendedDialogs(), PreferencesStore(tmp_path / "prefs.json")
    )
    scripts: Any = Scripts()
    projects.scripts = scripts
    return DemoService(projects, tmp_path / "copies")


def test_a_demo_opens_as_a_copy(tmp_path: Path) -> None:
    demos = service(tmp_path)
    listed = {demo["id"]: demo for demo in demos.list()}
    assert listed["sellar_mdf.py"]["title"] == "Sellar MDF"
    result = demos.open(DemoParams(id="external_code/external_code.py"))
    copy = tmp_path / "copies" / "external_code" / "external_code.py"
    assert result == {"cancelled": False, "reading": True, "path": str(copy)}
    assert (copy.parent / "solver.gpbwrap.json").is_file()  # With its folder.
    assert demos.projects.scripts.started == [copy]  # type: ignore[union-attr]
    with pytest.raises(BridgeError) as error:
        demos.open(DemoParams(id="../../secret.py"))
    assert error.value.code == "not_found"
