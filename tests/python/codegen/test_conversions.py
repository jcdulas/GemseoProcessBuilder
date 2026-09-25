"""Unit conversions and flattened arrays in generated scripts (SPEC § 5.5, § 5.6)."""

import importlib.util
import textwrap
from pathlib import Path
from types import ModuleType

import pytest
from builders import component
from builders import driver
from builders import project
from golden_projects import units_conversion
from numpy.testing import assert_allclose

from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import Project

MATRICES = '''
import numpy as np
from gemseo.core.discipline import Discipline


class Double(Discipline):
    """n = m / 2 + x, on 2x2 matrices."""

    def __init__(self):
        super().__init__("Double")
        self.io.input_grammar.update_from_data(
            {"m": np.zeros((2, 2)), "x": np.zeros(1)}
        )
        self.io.output_grammar.update_from_data({"n": np.zeros((2, 2))})
        self.default_input_data = {"m": np.ones((2, 2)), "x": np.ones(1)}

    def _run(self, input_data):
        return {"n": 0.5 * input_data["m"] + input_data["x"][0]}


class Half(Discipline):
    """m = n / 2 and f = the sum of n."""

    def __init__(self):
        super().__init__("Half")
        self.io.input_grammar.update_from_data({"n": np.zeros((2, 2))})
        self.io.output_grammar.update_from_data(
            {"m": np.zeros((2, 2)), "f": np.zeros(1)}
        )
        self.default_input_data = {"n": np.ones((2, 2))}

    def _run(self, input_data):
        return {"m": 0.5 * input_data["n"], "f": np.array([input_data["n"].sum()])}


class Distance(Discipline):
    """g = the squared distance from p to 0.3 everywhere."""

    def __init__(self):
        super().__init__("Distance")
        self.io.input_grammar.update_from_data({"p": np.zeros((2, 2))})
        self.io.output_grammar.update_from_data({"g": np.zeros(1)})
        self.default_input_data = {"p": np.ones((2, 2))}

    def _run(self, input_data):
        return {"g": np.array([((input_data["p"] - 0.3) ** 2).sum()])}
'''


def load(source: str, folder: Path) -> ModuleType:
    path = folder / "script.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"script_{id(folder)}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_consumers_receive_converted_values(tmp_path: Path) -> None:
    module = load(generate(units_conversion()).source, tmp_path)
    results = module.build_process().execute()
    # 10 mm wide: 1 mm = 0.001 m thick; 20 degC = 293.15 K.
    assert_allclose(results["thickness_m"], [0.001])
    assert_allclose(results["temperature_k"], [293.15])
    assert_allclose(results["stress"], [1000 * 0.001 + 293.15])


def test_disabled_conversions_are_left_out() -> None:
    model = units_conversion()
    stress = model.find("n-Stress")
    assert isinstance(stress, ComponentNode)
    stress.ports[0] = stress.ports[0].model_copy(update={"convert_units": False})
    source = generate(model).source
    assert "convert_thickness" not in source
    assert "convert_temperature_deg_c_to_k" in source


def matrix_component(
    name: str, cls: str, path: Path, ports: list[Port]
) -> ComponentNode:
    node = component(name, kind="python_class")
    node.config = {"module_path": str(path), "class": cls, "init_args": {}}
    node.ports = ports
    return node


@pytest.fixture
def matrices(tmp_path: Path) -> Path:
    path = tmp_path / "matrices.py"
    path.write_text(textwrap.dedent(MATRICES), encoding="utf-8")
    return path


def test_matrices_in_a_loop_are_exchanged_flattened(
    matrices: Path, tmp_path: Path
) -> None:
    def matrix(name: str, direction: str, flatten: bool = False) -> Port:
        return Port(local_name=name, direction=direction, shape=[2, 2], flatten=flatten)  # type: ignore[arg-type]

    double = matrix_component(
        "Double",
        "Double",
        matrices,
        [
            matrix("m", "in"),
            Port(local_name="x", direction="in"),
            matrix("n", "out", flatten=True),
        ],
    )
    half = matrix_component(
        "Half",
        "Half",
        matrices,
        [
            matrix("n", "in"),
            matrix("m", "out", flatten=True),
            Port(local_name="f", direction="out"),
        ],
    )
    source = generate(project(double, half)).source
    assert "class Reshape(Discipline):" in source
    assert 'name="Double_vectors"' in source
    module = load(source, tmp_path)
    results = module.build_process().execute()
    # The fixed point of n = n / 4 + 1 is 4 / 3.
    assert_allclose(results["n"], [4 / 3] * 4, rtol=1e-5)
    assert_allclose(results["f"], [16 / 3], rtol=1e-5)


def test_matrix_design_variable(matrices: Path, tmp_path: Path) -> None:
    distance = matrix_component(
        "Distance",
        "Distance",
        matrices,
        [
            Port(local_name="p", direction="in", shape=[2, 2], flatten=True),
            Port(local_name="g", direction="out"),
        ],
    )
    study = driver(
        "Study",
        "optimization",
        distance,
        config={
            "design_space": [
                {
                    "variable": "p",
                    "size": 4,
                    "lower": [-1.0] * 4,
                    "upper": [1.0] * 4,
                    "value": [0.5] * 4,
                }
            ],
            "objectives": [{"variable": "g"}],
            "formulation": {"name": "DisciplinaryOpt"},
            "algorithm": {"name": "SLSQP", "settings": {"max_iter": 20}},
        },
    )
    model: Project = project(study)
    module = load(generate(model, "n-Study").source, tmp_path)
    scenario = module.build_scenario()
    module.execute_scenario(scenario)
    assert_allclose(scenario.optimization_result.x_opt, [0.3] * 4, atol=1e-4)
