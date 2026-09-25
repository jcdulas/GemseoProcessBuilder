"""The wrapper editor methods that run in the UI process."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from builders import component
from builders import project

from gemseo_process_builder.app.api_executable import AddParams
from gemseo_process_builder.app.api_executable import ApplyParams
from gemseo_process_builder.app.api_executable import ExecutableController
from gemseo_process_builder.app.api_executable import PathParams
from gemseo_process_builder.app.api_executable import SaveParams
from gemseo_process_builder.app.api_executable import editable_spec
from gemseo_process_builder.app.api_executable import preview
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.runtime.spec import load_descriptor

EXAMPLE = Path(__file__).parents[3] / "examples" / "external_code"


@pytest.fixture
def controller(tmp_path: Path) -> ExecutableController:
    session = ProjectSession(tmp_path / "untitled.gpb.json.autosave")
    session.project = project(
        component("Solver", ["x"], [], kind="executable"),
        component("Other", ["x"], []),
    )
    worker: Any = None
    return ExecutableController(session, Bridge(MethodRegistry()), worker)


def test_applying_a_wrapper_sets_config_and_ports_in_one_step(
    controller: ExecutableController,
) -> None:
    spec = {
        "name": "Solver",
        "command": "run",
        "inputs": [{"name": "x", "size": 2, "default": [1, 2]}],
        "outputs": [{"name": "f", "unit": "m"}],
    }
    controller.apply(ApplyParams(id="n-Solver", spec=spec, base_folder="C:/w"))
    node = controller.session.project.find("n-Solver")
    assert node.config == {"spec": spec, "base_folder_path": "C:/w"}
    assert [(p.local_name, p.shape, p.unit) for p in node.ports] == [
        ("x", [2], None),
        ("f", [1], "m"),
    ]
    controller.session.document.undo()
    node = controller.session.project.find("n-Solver")
    assert node.config == {}
    assert [p.local_name for p in node.ports] == ["x"]


def test_adding_a_wrapper(controller: ExecutableController) -> None:
    path = str(EXAMPLE / "solver.gpbwrap.json")
    node_id = controller.add(AddParams(parent="n-root", descriptor_path=path))
    node = controller.session.project.find(node_id)
    assert (node.name, node.kind) == ("Solver_1", "executable")
    assert [p.local_name for p in node.ports] == ["x", "y", "f", "g"]


def test_applying_a_descriptor(controller: ExecutableController) -> None:
    path = str(EXAMPLE / "solver.gpbwrap.json")
    controller.apply(ApplyParams(id="n-Solver", descriptor_path=path))
    node = controller.session.project.find("n-Solver")
    assert node.config == {"descriptor_path": path}
    assert [p.local_name for p in node.ports] == ["x", "y", "f", "g"]
    with pytest.raises(BridgeError, match="executable component"):
        controller.apply(ApplyParams(id="n-Other", descriptor_path=path))


def test_a_descriptor_is_edited_with_inline_templates() -> None:
    edited = editable_spec(EXAMPLE / "solver.gpbwrap.json")
    template = edited["spec"]["templates"][0]
    assert "template" not in template
    assert "{{x" in template["content"]
    assert Path(edited["spec"]["files"][0]) == (EXAMPLE / "solver.py").resolve()
    assert edited["spec"]["rules"][0]["kind"] == "key_value"


def test_saving_writes_templates_and_relative_paths(
    controller: ExecutableController, tmp_path: Path
) -> None:
    edited = editable_spec(EXAMPLE / "solver.gpbwrap.json")
    target = tmp_path / "wrappers" / "copy.json"
    target.parent.mkdir()
    saved = Path(
        controller.save_descriptor(SaveParams(path=str(target), spec=edited["spec"]))
    )
    assert saved.name == "copy.gpbwrap.json"
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["templates"] == [{"template": "input.txt.tmpl", "target": "input.txt"}]
    assert (saved.parent / "input.txt.tmpl").read_text(encoding="utf-8") == (
        EXAMPLE / "input.tmpl"
    ).read_text(encoding="utf-8")
    spec, folder = load_descriptor(saved)
    assert (folder / spec.files[0]).resolve() == (EXAMPLE / "solver.py").resolve()


def test_saving_keeps_template_files(
    controller: ExecutableController, tmp_path: Path
) -> None:
    shutil.copy(EXAMPLE / "input.tmpl", tmp_path / "input.tmpl")
    spec = {
        "name": "S",
        "command": "run",
        "templates": [{"template": "input.tmpl", "target": "in.txt"}],
    }
    (tmp_path / "out").mkdir()
    saved = controller.save_descriptor(
        SaveParams(
            path=str(tmp_path / "out" / "s.gpbwrap.json"),
            spec=spec,
            base_folder=str(tmp_path),
        )
    )
    data = json.loads(Path(saved).read_text(encoding="utf-8"))
    assert data["templates"][0]["template"] == "../input.tmpl"


def test_invalid_specs_are_refused(
    controller: ExecutableController, tmp_path: Path
) -> None:
    with pytest.raises(BridgeError, match="Invalid wrapper"):
        controller.save_descriptor(
            SaveParams(path=str(tmp_path / "a.gpbwrap.json"), spec={"name": "A"})
        )


def test_samples_are_cut(controller: ExecutableController, tmp_path: Path) -> None:
    path = tmp_path / "out.txt"
    path.write_text("f = 1\n")
    sample = controller.read_sample(PathParams(path=str(path)))
    assert sample == {"name": "out.txt", "text": "f = 1\n", "truncated": False}
    with pytest.raises(BridgeError):
        controller.read_sample(PathParams(path=str(tmp_path / "none.txt")))


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ({"kind": "key_value", "variable": "f", "key": "f"}, 1.5),
        ({"kind": "marker", "variable": "f", "marker": "RESULTS", "column": 1}, 3.0),
        (
            {"kind": "table", "variable": "f", "marker": "RESULTS", "column": 1},
            [3.0, 4.0],
        ),
        ({"kind": "regex", "variable": "f", "pattern": r"f = (\S+)"}, 1.5),
    ],
)
def test_preview(rule: dict[str, Any], expected: Any) -> None:
    text = "f = 1.5\nRESULTS\n1 3.0\n2 4.0\n\nend\n"
    result = preview(rule, text)
    assert result["error"] == ""
    assert result["value"] == pytest.approx(expected)


def test_preview_explains_failures() -> None:
    assert "Incomplete rule" in preview({"kind": "key_value"}, "")["error"]
    missing = preview({"kind": "key_value", "variable": "f", "key": "z"}, "f = 1")
    assert missing["value"] is None
    assert missing["error"]
