"""Working examples of components created from the inspector."""

import filecmp
import importlib.util
import io
import sys
from pathlib import Path
from typing import Any

import pytest
from builders import component
from builders import project

from gemseo_process_builder.app.api_component_examples import TEMPLATES
from gemseo_process_builder.app.api_component_examples import ComponentExamples
from gemseo_process_builder.app.api_component_examples import ExampleParams
from gemseo_process_builder.app.api_component_examples import latin_hypercube
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.results import reader
from gemseo_process_builder.results.store import RunStore
from gemseo_process_builder.runtime.spec import load_descriptor
from gemseo_process_builder.workers.component_methods import introspect
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.surrogate_methods import train

EXAMPLES = Path(__file__).parents[3] / "examples" / "external_code"


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


@pytest.fixture
def examples(tmp_path: Path) -> ComponentExamples:
    session = ProjectSession(tmp_path / "wing.gpb.json")
    session.project = project(
        component("F", kind="python_function"),
        component("C", kind="python_class"),
        component("E", kind="executable"),
        component("S", kind="surrogate"),
        component("A"),
    )
    return ComponentExamples(session, Bridge(MethodRegistry()), RunStore(session))


def ports_of(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    return {(p["local_name"], p["direction"]): p for p in introspect(kind, config)}


def test_a_python_function(examples: ComponentExamples, tmp_path: Path) -> None:
    result = examples.create(ExampleParams(id="n-F", path=str(tmp_path / "area")))
    path = tmp_path / "area.py"
    assert result == {"files": [str(path)]}
    config = examples.session.project.find("n-F").config
    assert config == {"module_path": str(path), "function": "wing_area"}
    ports = ports_of("python_function", config)
    assert set(ports) == {
        ("span", "in"),
        ("chord", "in"),
        ("area", "out"),
        ("aspect_ratio", "out"),
    }
    assert ports["span", "in"]["default"] == [10.0]
    with pytest.raises(BridgeError, match="already exist"):
        examples.create(ExampleParams(id="n-F", path=str(path)))


def test_a_python_class_that_computes(
    examples: ComponentExamples, tmp_path: Path
) -> None:
    path = tmp_path / "wing.py"
    examples.create(ExampleParams(id="n-C", path=str(path)))
    assert "        area = span * chord\n" in path.read_text("utf-8")
    spec = importlib.util.spec_from_file_location("wing_example", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["wing_example"] = module
    spec.loader.exec_module(module)
    outputs = module.Wing().execute()
    assert (outputs["area"][0], outputs["aspect_ratio"][0]) == (20.0, 5.0)


def test_an_executable_wrapper(examples: ComponentExamples, tmp_path: Path) -> None:
    descriptor = tmp_path / "wrapper" / "my_solver.gpbwrap.json"
    result = examples.create(ExampleParams(id="n-E", path=str(descriptor)))
    assert sorted(Path(file).name for file in result["files"]) == [
        "input.tmpl",
        "my_solver.gpbwrap.json",
        "solver.py",
    ]
    spec, folder = load_descriptor(descriptor)
    assert (spec.name, folder) == ("Solver", descriptor.parent)
    assert examples.session.project.find("n-E").config == {
        "descriptor_path": str(descriptor)
    }
    with pytest.raises(BridgeError, match=r"solver\.py"):
        examples.create(
            ExampleParams(
                id="n-E", path=str(tmp_path / "wrapper" / "other.gpbwrap.json")
            )
        )


def test_the_templates_are_the_examples_of_the_repository() -> None:
    for name in ("solver.py", "input.tmpl", "solver.gpbwrap.json"):
        assert filecmp.cmp(TEMPLATES / "external_code" / name, EXAMPLES / name, False)


def test_samples_to_train_a_surrogate_on(
    examples: ComponentExamples, tmp_path: Path
) -> None:
    sample = examples.samples()
    folder = examples.runs.folder_of(sample["run"])
    assert folder is not None
    table = reader.load(folder)
    assert len(table.values) == 40
    assert reader.summary(folder)["name"] == "Example samples of a wing"
    result = train(
        str(folder),
        sample["inputs"],
        sample["outputs"],
        sample["algorithm"],
        {},
        3,
        str(tmp_path / "model.pkl"),
    )
    assert result["quality"]["area"]["r2_cv"][0] > 0.95


def test_latin_hypercube_fills_each_slice() -> None:
    samples = latin_hypercube({"x": (0.0, 1.0)}, 10)
    assert sorted(int(value * 10) for value in samples["x"]) == list(range(10))


def test_no_example_for_other_kinds(examples: ComponentExamples) -> None:
    with pytest.raises(BridgeError, match="no example of analytic"):
        examples.create(ExampleParams(id="n-A", path="x.py"))
