import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from gemseo_process_builder.core.migrations import ProjectFileError
from gemseo_process_builder.core.migrations import migrate
from gemseo_process_builder.core.model import CURRENT_SCHEMA_VERSION
from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.model import path_of
from gemseo_process_builder.core.paths import to_absolute
from gemseo_process_builder.core.paths import to_relative
from gemseo_process_builder.core.serialization import dumps
from gemseo_process_builder.core.serialization import load_project
from gemseo_process_builder.core.serialization import loads
from gemseo_process_builder.core.serialization import project_name_from_path
from gemseo_process_builder.core.serialization import save_project

DATA = Path(__file__).parent.parent / "data"
SELLAR = DATA / "sellar_v1.gpb.json"


def test_sellar_round_trip_is_byte_identical() -> None:
    text = SELLAR.read_text(encoding="utf-8")
    assert dumps(loads(text, DATA), DATA) == text


def test_sellar_content() -> None:
    project = load_project(SELLAR)
    optimizer = project.find("n-opt")
    assert isinstance(optimizer, DriverNode)
    assert optimizer.kind == "optimization"
    assert [child.name for child in optimizer.children] == [
        "Sellar1",
        "Sellar2",
        "SellarSystem",
    ]
    sellar_1 = project.find("n-sellar1")
    assert isinstance(sellar_1, ComponentNode)
    assert sellar_1.port("x_local", "in") is not None
    assert path_of(project, "n-sellar1") == "Model.Optimizer.Sellar1"
    assert project.parent_of("n-sellar1") is optimizer
    assert project.parent_of("n-root") is None


def test_paths_are_absolute_in_memory_and_relative_in_files() -> None:
    project = load_project(SELLAR)
    helper = project.find("n-helper")
    assert isinstance(helper, ComponentNode)
    assert (
        Path(helper.config["module_path"])
        == (DATA / "disciplines" / "helper.py").resolve()
    )
    assert Path(project.settings.catalog_paths[0]).is_absolute()
    assert '"module_path": "disciplines/helper.py"' in dumps(project, DATA)


def test_relative_path_conversion(tmp_path: Path) -> None:
    folder = tmp_path / "project"
    outside = str(tmp_path / "lib" / "x.py")
    assert to_relative(outside, folder) == "../lib/x.py"
    assert Path(to_absolute("../lib/x.py", folder)) == Path(outside).resolve()
    assert to_relative("relative/already.py", folder) == "relative/already.py"
    assert to_relative("", folder) == ""


def test_empty_project_file_is_minimal(tmp_path: Path) -> None:
    data = json.loads(dumps(Project(), tmp_path))
    assert data["schema_version"] == CURRENT_SCHEMA_VERSION
    assert data["root"] == {"id": "n-root", "name": "Model", "type": "assembly"}
    assert loads(dumps(Project(), tmp_path), tmp_path).root.name == "Model"


def test_save_and_load(tmp_path: Path) -> None:
    project = Project()
    project.root.children.append(
        ComponentNode(
            name="Aero",
            kind="analytic",
            config={"expressions": {"y": "x**2"}},
            ports=[Port(local_name="x", direction="in", unit="m")],
        )
    )
    path = tmp_path / "sub" / "p.gpb.json"
    save_project(project, path)
    assert load_project(path).root.children[0].name == "Aero"
    assert not list(path.parent.glob("*.tmp"))


def test_duplicate_sibling_names_are_rejected() -> None:
    with pytest.raises(ValidationError, match="several children named A"):
        AssemblyNode(
            name="Model",
            children=[
                ComponentNode(name="A", kind="analytic"),
                AssemblyNode(name="A"),
            ],
        )


@pytest.mark.parametrize("name", ["1abc", "with space", "", "é"])
def test_invalid_node_names(name: str) -> None:
    with pytest.raises(ValidationError, match="Invalid name"):
        ComponentNode(name=name, kind="analytic")


def test_invalid_port_names() -> None:
    with pytest.raises(ValidationError, match="without ':'"):
        Port(local_name="ns:x", direction="in")


def test_duplicate_ports_are_rejected() -> None:
    with pytest.raises(ValidationError, match="two inputs named 'x'"):
        ComponentNode(
            name="C",
            kind="analytic",
            ports=[
                Port(local_name="x", direction="in"),
                Port(local_name="x", direction="in"),
            ],
        )


def test_same_name_as_input_and_output_is_allowed() -> None:
    component = ComponentNode(
        name="C",
        kind="analytic",
        ports=[
            Port(local_name="x", direction="in"),
            Port(local_name="x", direction="out"),
        ],
    )
    assert len(component.ports) == 2


def test_node_kinds_are_parsed() -> None:
    data = {
        "root": {
            "id": "n-root",
            "name": "Model",
            "type": "assembly",
            "children": [
                {"id": "n-a", "name": "A", "type": "component", "kind": "analytic"},
                {"id": "n-d", "name": "D", "type": "driver", "kind": "doe"},
                {"id": "n-b", "name": "B", "type": "assembly", "mode": "mda"},
            ],
        }
    }
    project = Project.model_validate(data)
    assert [type(child) for child in project.root.children] == [
        ComponentNode,
        DriverNode,
        AssemblyNode,
    ]


def test_duplicate_ids_are_rejected() -> None:
    with pytest.raises(ValidationError, match="share the same id"):
        Project(
            root=AssemblyNode(
                id="n-root",
                name="Model",
                children=[
                    ComponentNode(id="n-x", name="A", kind="analytic"),
                    ComponentNode(id="n-x", name="B", kind="analytic"),
                ],
            )
        )


def test_migration_from_version_0(tmp_path: Path) -> None:
    version_0 = {
        "root": {"id": "n-root", "name": "Model", "type": "assembly"},
        "layout": {"n-root": {"x": 1, "y": 2}},
    }
    project = loads(json.dumps(version_0), tmp_path)
    assert project.schema_version == CURRENT_SCHEMA_VERSION
    assert project.layout.nodes["n-root"].x == 1


def test_file_from_a_newer_version_is_refused() -> None:
    with pytest.raises(ProjectFileError, match="newer version"):
        migrate({"schema_version": CURRENT_SCHEMA_VERSION + 1})


@pytest.mark.parametrize("text", ["not json", "[1, 2]", '{"root": {"name": "1"}}'])
def test_invalid_files(text: str, tmp_path: Path) -> None:
    with pytest.raises(ProjectFileError):
        loads(text, tmp_path)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ProjectFileError, match="Cannot read"):
        load_project(tmp_path / "missing.gpb.json")


def test_project_name_from_path() -> None:
    assert project_name_from_path(Path("a/Sellar.gpb.json")) == "Sellar"
    assert project_name_from_path(Path("a/other.json")) == "other"
