"""Nested drivers: adapters, BiLevel sub-scenarios and nested MDAs (SPEC § 6.3).

The examples run with reduced settings (2 or 3 iterations, 2 samples) so that
each test stays under one second; the example files keep realistic settings.
"""

import importlib.util
import io
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from builders import component
from builders import driver
from builders import project
from gemseo import create_design_space
from gemseo import create_scenario
from gemseo.disciplines.scenario_adapters.mdo_scenario_adapter import MDOScenarioAdapter
from gemseo.problems.mdo.sellar.sellar_1 import Sellar1
from gemseo.problems.mdo.sellar.sellar_2 import Sellar2
from gemseo.problems.mdo.sellar.sellar_system import SellarSystem
from gemseo.problems.mdo.sobieski.core.design_space import SobieskiDesignSpace
from gemseo.problems.mdo.sobieski.disciplines import SobieskiAerodynamics
from gemseo.problems.mdo.sobieski.disciplines import SobieskiMission
from gemseo.problems.mdo.sobieski.disciplines import SobieskiPropulsion
from gemseo.problems.mdo.sobieski.disciplines import SobieskiStructure
from golden_projects import example
from numpy.testing import assert_allclose

from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.workers.codegen_methods import dry_run
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel

SUB_ITERATIONS = 3
SYSTEM_ITERATIONS = 2


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


def load(source: str, folder: Path) -> ModuleType:
    """Import a generated script, as the runner does."""
    path = folder / "script.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"script_{id(folder)}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def settings(p: Project, node_id: str, **values: Any) -> None:
    node = p.find(node_id)
    assert isinstance(node, DriverNode)
    node.config["algorithm"]["settings"].update(values)


def reduced_bilevel() -> Project:
    p = example("sobieski_bilevel")
    settings(p, "n-system", max_iter=SYSTEM_ITERATIONS)
    for name in ("propulsion", "aerodynamics", "structure"):
        settings(p, f"n-{name}-optimizer", max_iter=SUB_ITERATIONS)
    return p


def bilevel_reference() -> Any:
    """GEMSEO's SSBJ BiLevel example, written by hand with the same settings."""
    design_space = SobieskiDesignSpace()
    scenarios = []
    for discipline, objective, variable, maximize, constraint in (
        (SobieskiPropulsion(), "y_34", "x_3", False, "g_3"),
        (SobieskiAerodynamics(), "y_24", "x_2", True, "g_2"),
        (SobieskiStructure(), "y_11", "x_1", True, "g_1"),
    ):
        scenario = create_scenario(
            [discipline],
            objective,
            design_space.filter(variable, copy=True),
            maximize_objective=maximize,
            formulation_name="DisciplinaryOpt",
        )
        scenario.add_constraint(constraint, constraint_type="ineq")
        scenario.set_algorithm(algo_name="SLSQP", max_iter=SUB_ITERATIONS)
        scenarios.append(scenario)
    system = create_scenario(
        [*scenarios, SobieskiMission()],
        "y_4",
        design_space.filter("x_shared", copy=True),
        maximize_objective=True,
        formulation_name="BiLevel",
        apply_cstr_tosub_scenarios=False,
    )
    system.add_constraint(["g_1", "g_2", "g_3"], constraint_type="ineq")
    system.execute(algo_name="COBYQA", max_iter=SYSTEM_ITERATIONS)
    return system


def test_bilevel_matches_hand_written_gemseo(tmp_path: Path) -> None:
    module = load(generate(reduced_bilevel(), "n-system").source, tmp_path)
    scenario = module.build_scenario()
    module.execute_scenario(scenario)
    reference = bilevel_reference()
    assert_allclose(
        scenario.optimization_result.f_opt, reference.optimization_result.f_opt
    )
    assert_allclose(
        scenario.optimization_result.x_opt, reference.optimization_result.x_opt
    )


def reduced_doe() -> Project:
    p = example("doe_around_optimization")
    settings(p, "n-study", n_samples=2)
    settings(p, "n-optimizer", max_iter=5)
    return p


def doe_reference() -> Any:
    """The DOE around the Sellar optimization, written by hand."""
    design_space = create_design_space()
    design_space.add_variable("x_1", lower_bound=0.0, upper_bound=10.0, value=1.0)
    design_space.add_variable("x_2", lower_bound=0.0, upper_bound=10.0, value=1.0)
    design_space.add_variable(
        "x_shared",
        size=2,
        lower_bound=[-10.0, 0.0],
        upper_bound=[10.0, 10.0],
        value=[4.0, 3.0],
    )
    optimization = create_scenario(
        [Sellar1(), Sellar2(), SellarSystem()],
        "obj",
        design_space,
        formulation_name="MDF",
        main_mda_name="MDAGaussSeidel",
    )
    optimization.add_constraint("c_1", constraint_type="ineq")
    optimization.add_constraint("c_2", constraint_type="ineq")
    optimization.set_algorithm(algo_name="SLSQP", max_iter=5)
    adapter = MDOScenarioAdapter(
        optimization, ["alpha"], ["obj", "x_1", "x_shared"], reset_x0_before_opt=True
    )
    alpha = create_design_space()
    alpha.add_variable("alpha", lower_bound=3.0, upper_bound=4.0, value=3.16)
    study = create_scenario(
        [adapter],
        "obj",
        alpha,
        scenario_type="DOE",
        formulation_name="DisciplinaryOpt",
    )
    study.execute(algo_name="LHS", n_samples=2, seed=1)
    return study


def samples(scenario: Any) -> Any:
    return scenario.to_dataset().get_view(variable_names=["alpha", "obj"]).to_numpy()


def test_doe_around_optimization_matches_hand_written_gemseo(tmp_path: Path) -> None:
    module = load(generate(reduced_doe(), "n-study").source, tmp_path)
    scenario = module.build_scenario()
    module.execute_scenario(scenario)
    assert_allclose(samples(scenario), samples(doe_reference()))


@pytest.mark.parametrize(
    ("name", "target"),
    [("sobieski_bilevel", "n-system"), ("doe_around_optimization", "n-study")],
)
def test_examples_pass_the_dry_run(name: str, target: str) -> None:
    script = generate(example(name), target)
    assert dry_run(script.source, script.mapping) == []


def test_errors_in_a_nested_scenario_are_attached_to_its_driver() -> None:
    p = example("doe_around_optimization")
    optimizer = p.find("n-optimizer")
    assert isinstance(optimizer, DriverNode)
    optimizer.config["constraints"] = [{"variable": "c_9"}]
    script = generate(p, "n-study")
    (issue,) = dry_run(script.source, script.mapping)
    assert issue["node"] == "n-optimizer"
    assert "c_9" in issue["message"]


def test_mapping_names_the_nested_scenarios() -> None:
    mapping = generate(example("sobieski_bilevel"), "n-system").mapping
    assert mapping["scenarios"]["n-structure-optimizer"] == "StructureOptimizer"
    assert mapping["disciplines"]["n-structure"] == "Structure"
    assert mapping["disciplines"]["n-structure-optimizer"] == (
        "StructureOptimizer_adapter"
    )


def test_nested_mda_driver_becomes_an_mda() -> None:
    loop = driver(
        "Loop",
        "mda",
        component(
            "A", ins=["x", "b"], outs=["a"], config={"expressions": {"a": "x + 0.5*b"}}
        ),
        component("B", ins=["a"], outs=["b"], config={"expressions": {"b": "0.5*a"}}),
    )
    source = generate(
        project(
            loop,
            component("C", ins=["a"], outs=["c"], config={"expressions": {"c": "2*a"}}),
        )
    ).source
    assert "def build_loop() -> Discipline:" in source
    assert '"""Create the Loop MDA."""' in source
    assert 'create_mda("MDAChain", [a, b], name="Loop")' in source


def test_nested_parametric_study_gets_its_samples() -> None:
    inner = driver(
        "Sweep",
        "parametric",
        component("F", ins=["x"], outs=["f"], config={"expressions": {"f": "x**2"}}),
        config={
            "levels": [{"variable": "x", "lower": 0.0, "upper": 1.0, "count": 3}],
            "responses": ["f"],
            "interface": {"outputs": ["f"]},
        },
    )
    source = generate(
        project(
            inner,
            component("G", ins=["f"], outs=["g"], config={"expressions": {"g": "f"}}),
        )
    ).source
    assert "def build_sweep_samples() -> NDArray[float64]:" in source
    assert (
        'scenario.set_algorithm(algo_name="CustomDOE", samples=build_sweep_samples())'
        in source
    )
