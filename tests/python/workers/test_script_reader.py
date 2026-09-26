"""Reading GEMSEO scripts written by hand into projects."""

import io
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.script_reader import grid_levels
from gemseo_process_builder.workers.script_reader import import_stopping_studies
from gemseo_process_builder.workers.script_reader import read_script
from gemseo_process_builder.workers.script_reader import script_metadata
from gemseo_process_builder.workers.server import WorkerError

SCRIPTS = Path(__file__).parent / "scripts"


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


def driver_of(result: dict[str, Any]) -> dict[str, Any]:
    Project.model_validate(result["project"])  # A valid project.
    (driver,) = result["project"]["root"]["children"]
    return driver


def test_the_tutorial_of_gemseo(tmp_path: Path) -> None:
    script = tmp_path / "sellar.py"
    script.write_text((SCRIPTS / "sellar_tutorial.py").read_text("utf-8"), "utf-8")
    result = read_script(script)
    driver = driver_of(result)
    assert (driver["kind"], driver["name"]) == ("optimization", "Optimizer")
    config = driver["config"]
    assert config["objectives"] == [{"variable": "obj", "sense": "minimize"}]
    assert config["constraints"] == [
        {"variable": "c_1", "type": "ineq", "operator": "<=", "value": 0.0},
        {"variable": "c_2", "type": "ineq", "operator": ">=", "value": 0.5},
    ]
    assert config["observables"] == ["y_1"]
    assert config["algorithm"] == {"name": "SLSQP", "settings": {"max_iter": 10}}
    assert config["formulation"]["name"] == "MDF"
    assert [(v["variable"], v["size"], v["value"]) for v in config["design_space"]] == [
        ("x_1", 1, [1.0]),
        ("x_shared", 2, [4.0, 3.0]),
    ]
    assert [c["config"]["class"] for c in driver["children"]] == [
        "Sellar1",
        "Sellar2",
        "SellarSystem",
    ]
    # The study stopped before running: no post-processing was saved.
    assert not list(tmp_path.glob("*.png"))
    assert result["warnings"] == []


def test_functions_classes_and_values_of_the_script() -> None:
    result = read_script(SCRIPTS / "wing_study.py")
    driver = driver_of(result)
    assert driver["name"] == "Sizing"
    assert driver["config"]["algorithm"]["name"] == "NLOPT_COBYLA"
    area, lift, cost = driver["children"]
    script = str((SCRIPTS / "wing_study.py").resolve())
    assert area["config"] == {"module_path": script, "function": "wing_area"}
    assert lift["config"] == {
        "module_path": script,
        "class": "Lift",
        "init_args": {"density": 1.1},
    }
    assert cost["config"] == {"expressions": {"cost": "100*span + 50*chord"}}
    # The value set on the discipline after it was built: typed in the diagram.
    assert cost["ports"] == [
        {
            "local_name": "chord",
            "direction": "in",
            "default": 3.0,
            "default_text": "3.0",
        }
    ]


def test_a_script_without_scenario_gives_its_process() -> None:
    result = read_script(SCRIPTS / "mda_only.py")
    mda = result["project"]["root"]  # The model itself.
    assert (mda["type"], mda["mode"], mda["name"]) == ("assembly", "mda", "Model")
    assert [child["name"] for child in mda["children"]] == ["First", "Second"]


def test_scripts_that_cannot_be_read(tmp_path: Path) -> None:
    empty = tmp_path / "empty.py"
    empty.write_text("import gemseo\n\nx = 1\n", "utf-8")
    with pytest.raises(WorkerError, match="nothing to read"):
        read_script(empty)
    broken = tmp_path / "broken.py"
    broken.write_text("import gemseo\n\nraise ValueError('no data file')\n", "utf-8")
    with pytest.raises(WorkerError, match="ValueError: no data file"):
        read_script(broken)


def test_importing_a_script_does_not_run_its_study() -> None:
    module = import_stopping_studies(SCRIPTS / "wing_study.py")
    assert module.wing_area(3.0, 2.0) == 6.0
    assert module.Lift.__name__ == "Lift"


def test_grids_of_samples_become_levels() -> None:
    variables = [{"variable": "x", "size": 1}, {"variable": "y", "size": 1}]
    samples = [[x, y] for x in (0.0, 0.5, 1.0) for y in (2.0, 7.0)]
    assert grid_levels(samples, variables) == [
        {"variable": "x", "lower": 0.0, "upper": 1.0, "count": 3},
        {"variable": "y", "mode": "list", "values": [2.0, 7.0]},
    ]
    assert grid_levels(samples[:-1], variables) is None
    assert grid_levels([[0.0], [1.0]], [{"variable": "x", "size": 2}]) is None
    assert "wing_study" not in sys.modules  # Read under a unique name.


def test_isolated_instances_and_their_links() -> None:
    script = Path(__file__).parents[1] / "codegen" / "golden" / "isolated_instances.py"
    project = Project.model_validate(read_script(script)["project"])
    front, rear, total = project.root.children
    assert (front.isolated, rear.isolated, total.isolated) == (True, True, False)
    assert {port.local_name: port.global_name for port in front.ports} == {
        "density": "density",  # Shared, not namespaced.
        "volume": None,
        "mass": None,
    }
    assert [
        (link.source.node, link.source.port, link.target.port) for link in project.links
    ] == [(front.id, "mass", "front_mass"), (rear.id, "mass", "rear_mass")]
    assert project.metadata.name == "Masses"


def test_the_name_and_description_come_from_the_docstring(tmp_path: Path) -> None:
    written = tmp_path / "wing.py"
    written.write_text(
        '"""Wing.\n\nA wing.\n\nIts sizing.\n\n'
        'Generated by GEMSEO Process Builder 0.1.0 on 2026-09-26.\n"""\n',
        "utf-8",
    )
    assert script_metadata(written) == {
        "name": "Wing",
        "description": "A wing.\n\nIts sizing.",
    }
    by_hand = tmp_path / "study.py"
    by_hand.write_text('"""My study.\n\nOf a wing."""\n', "utf-8")
    assert script_metadata(by_hand) == {
        "name": "study",
        "description": "My study.\n\nOf a wing.",
    }
    by_hand.write_text("x = 1\n", "utf-8")
    assert script_metadata(by_hand)["description"] == "Read from study.py."


def test_an_optimization_as_a_step_of_a_sequence() -> None:
    script = Path(__file__).parents[3] / "examples" / "optimization_sequence.py"
    root = read_script(script)["project"]["root"]
    assert (root["type"], root["mode"]) == ("assembly", "chain")
    kinds = [child.get("kind") for child in root["children"]]
    assert kinds == ["analytic", "optimization", "analytic"]


def test_a_study_in_several_files_with_every_kind_of_component(
    tmp_path: Path,
) -> None:
    demo = Path(__file__).parents[3] / "examples" / "demoBiLevel"
    folder = tmp_path / "demo"
    shutil.copytree(
        demo, folder, ignore=shutil.ignore_patterns("models", "__pycache__")
    )
    result = read_script(folder / "demo_bilevel.py")
    assert result["warnings"] == []
    project = Project.model_validate(result["project"])
    components = {
        node.name: node
        for node, _ in iter_nodes(project.root)
        if node.type == "component"
    }
    assert {node.kind for node in components.values()} == {
        "analytic",
        "python_function",
        "python_class",
        "executable",
        "surrogate",
    }
    # The surrogate the script trained and pickled itself.
    assert components["Maintenance"].config["model_path"] == str(
        (folder / "models" / "maintenance.pkl").resolve()
    )
    assert components["OperatingCost"].config["module_path"] == str(
        (folder / "economics.py").resolve()
    )
    emissions = {
        port.local_name: port.global_name for port in components["Emissions"].ports
    }
    assert emissions["flight_range"] == "y_4"
    system = project.root.children[0]
    assert system.config["observables"] == ["cost", "co2", "noise_db", "maintenance"]
    # The algorithm set on each sub-optimization, with its settings.
    propulsion = system.children[0]
    assert propulsion.config["algorithm"] == {
        "name": "SLSQP",
        "settings": {"max_iter": 30},
    }


def test_the_modules_of_a_study_are_read_again(tmp_path: Path) -> None:
    helper = tmp_path / "formulas.py"
    helper.write_text('AREA = "span*chord"\n', "utf-8")
    script = tmp_path / "study.py"
    script.write_text(
        "from gemseo.disciplines.analytic import AnalyticDiscipline\n"
        "from formulas import AREA\n\n"
        'AnalyticDiscipline({"area": AREA}, name="Wing").execute()\n',
        "utf-8",
    )

    def formula() -> str:
        root = read_script(script)["project"]["root"]
        return root["children"][0]["config"]["expressions"]["area"]

    assert formula() == "span*chord"
    helper.write_text('AREA = "0.5*span*chord"\n', "utf-8")  # Edited since.
    assert formula() == "0.5*span*chord"


def test_a_bilevel_study_on_post_optimal_sensitivities(tmp_path: Path) -> None:
    demo = Path(__file__).parents[3] / "examples" / "wingBiLevel100k"
    folder = tmp_path / "demo"
    shutil.copytree(demo, folder, ignore=shutil.ignore_patterns("__pycache__"))
    # 100 sections instead of 50,000: the same study, read in a moment.
    for module in ("twist_optimizer/aerodynamics.py", "wing_box_optimizer/wing_box.py"):
        path = folder / module
        text = path.read_text("utf-8").replace("STATIONS = 50_000", "STATIONS = 100")
        path.write_text(text, "utf-8")
    result = read_script(folder / "wing_bilevel_100k.py")
    assert result["warnings"] == []
    project = Project.model_validate(result["project"])
    (system,) = project.root.children
    assert [child.name for child in system.children] == [
        "Loads",
        "WingBoxOptimizer",
        "TwistOptimizer",
        "Performance",
    ]
    wing_box = system.children[1]
    # The adapters give only their optima: the post-optimal analysis differentiates
    # them.
    assert wing_box.config["interface"] == {
        "inputs": ["area", "span", "load_max"],
        "outputs": ["weight"],
    }
    assert wing_box.config["algorithm"]["name"] == "NLOPT_MMA"
    assert wing_box.config["algorithm"]["settings"]["log_problem"] is False
    (thickness,) = wing_box.config["design_space"]
    assert (thickness["variable"], thickness["size"]) == ("relative_thickness", 100)
    assert [c["variable"] for c in system.config["constraints"]] == [
        "wing_loading",
        "weight_margin",
    ]
