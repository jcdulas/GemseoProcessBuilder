"""Opening a GEMSEO script as a project, in the UI process."""

from pathlib import Path
from typing import Any

from gemseo_process_builder.app.api_project import ProjectController
from gemseo_process_builder.app.benchmark_mode import UnattendedDialogs
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.component_service import ComponentService
from gemseo_process_builder.app.preferences import PreferencesStore
from gemseo_process_builder.app.project_session import ProjectSession

READ = {
    "project": {
        "metadata": {"name": "wing_study"},
        "root": {
            "type": "assembly",
            "id": "n-root",
            "name": "Model",
            "children": [
                {
                    "type": "component",
                    "id": "n-cost",
                    "kind": "analytic",
                    "name": "Cost",
                    "config": {"expressions": {"cost": "100*span + 50*chord"}},
                    "ports": [
                        {
                            "local_name": "chord",
                            "direction": "in",
                            "default": 3.0,
                            "default_text": "3.0",
                        }
                    ],
                }
            ],
        },
    },
    "warnings": ["Something left out."],
}


class Worker:
    """Records the requests of the component service."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def request(
        self, method: str, params: dict[str, Any], *args: Any, **kwargs: Any
    ) -> str:
        self.requests.append((method, params))
        return "1"


def controller(
    tmp_path: Path,
) -> tuple[ProjectController, list[tuple[str, Any]], ComponentService]:
    session = ProjectSession(tmp_path / "untitled.gpb.json.autosave")
    bridge = Bridge(MethodRegistry())
    events: list[tuple[str, Any]] = []
    bridge.emit_event = lambda name, payload: events.append((name, payload))  # type: ignore[method-assign]
    worker: Any = Worker()
    components = ComponentService(session, bridge, worker)
    preferences = PreferencesStore(tmp_path / "preferences.json")
    projects = ProjectController(session, bridge, UnattendedDialogs(), preferences)
    return projects, events, components


def test_a_script_read_replaces_the_project(tmp_path: Path) -> None:
    projects, events, components = controller(tmp_path)
    script = tmp_path / "wing_study.py"
    projects._script_read(script, {"ok": True, "result": READ})
    session = projects.session
    assert (session.path, session.dirty) == (script.resolve(), True)
    assert session.project.metadata.name == "wing_study"
    names = [name for name, _ in events]
    assert "document.reset" in names
    assert (
        "project.scriptRead",
        {"path": str(script), "warnings": ["Something left out."]},
    ) in events
    # Its components only have their typed values: they are all read again.
    assert components._queued == {"n-cost"}


def test_a_script_that_cannot_be_read(tmp_path: Path) -> None:
    projects, events, _ = controller(tmp_path)
    failure = {
        "ok": False,
        "error": {"code": "script_error", "message": "The script failed."},
    }
    projects._script_read(tmp_path / "broken.py", failure)
    assert events[-1] == (
        "project.scriptFailed",
        {"path": str(tmp_path / "broken.py"), "message": "The script failed."},
    )
    assert projects.session.project.metadata.name == "Untitled"
