"""Scenario scripts: generation details and equivalence with hand-written GEMSEO.

The examples run with reduced settings (a few iterations or samples) so that
each test stays under one second; the example files keep realistic settings.
"""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from builders import component
from builders import driver
from builders import project
from doe_runs import rosenbrock_run
from gemseo import create_design_space
from gemseo import create_mda
from gemseo import create_scenario
from gemseo import from_pickle
from gemseo.disciplines.analytic import AnalyticDiscipline
from gemseo.disciplines.surrogate import SurrogateDiscipline
from gemseo.problems.mdo.sellar.sellar_1 import Sellar1
from gemseo.problems.mdo.sellar.sellar_2 import Sellar2
from gemseo.problems.mdo.sellar.sellar_system import SellarSystem
from golden_projects import example
from numpy import array
from numpy.testing import assert_allclose

from gemseo_process_builder.codegen.generator import CodegenError
from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.workers.surrogate_methods import train

ROSENBROCK = "(1 - x)**2 + 100*(y - x**2)**2"


def load(source: str, folder: Path) -> ModuleType:
    """Import a generated script, as the runner does."""
    path = folder / "script.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"script_{id(folder)}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(p: Project, target: str, folder: Path) -> Any:
    """Build and execute the scenario of a generated script."""
    module = load(generate(p, target).source, folder)
    scenario = module.build_scenario()
    module.execute_scenario(scenario)
    return scenario


def with_settings(p: Project, target: str, **settings: Any) -> Project:
    node = p.find(target)
    assert node is not None
    algorithm = node.config["algorithm"]  # type: ignore[union-attr]
    node.config = {  # type: ignore[union-attr]
        **node.config,  # type: ignore[union-attr]
        "algorithm": {**algorithm, "settings": {**algorithm["settings"], **settings}},
    }
    return p


def sellar_reference(
    formulation: str, disciplines: list[Any] | None = None, **settings: Any
) -> Any:
    """The Sellar optimization written by hand."""
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
    if formulation == "IDF":
        design_space.add_variable(
            "y_1", lower_bound=-100.0, upper_bound=100.0, value=1.0
        )
        design_space.add_variable(
            "y_2", lower_bound=-100.0, upper_bound=100.0, value=1.0
        )
    scenario = create_scenario(
        disciplines or [Sellar1(), Sellar2(), SellarSystem()],
        "obj",
        design_space,
        formulation_name=formulation,
        **settings,
    )
    scenario.add_constraint("c_1", constraint_type="ineq")
    scenario.add_constraint("c_2", constraint_type="ineq")
    scenario.execute(algo_name="SLSQP", max_iter=2)
    return scenario


@pytest.mark.parametrize(
    ("name", "formulation", "settings"),
    [
        ("sellar_mdf", "MDF", {"main_mda_name": "MDAGaussSeidel"}),
        ("sellar_idf", "IDF", {}),
    ],
)
def test_sellar_matches_hand_written_gemseo(
    name: str, formulation: str, settings: dict[str, Any], tmp_path: Path
) -> None:
    generated = run(
        with_settings(example(name), "n-optimizer", max_iter=2), "n-optimizer", tmp_path
    )
    reference = sellar_reference(formulation, **settings)
    assert_allclose(
        generated.optimization_result.f_opt,
        reference.optimization_result.f_opt,
        rtol=1e-8,
    )
    assert_allclose(
        generated.optimization_result.x_opt,
        reference.optimization_result.x_opt,
        rtol=1e-8,
    )


def test_rosenbrock_doe_matches_hand_written_gemseo(tmp_path: Path) -> None:
    p = with_settings(example("rosenbrock_doe"), "n-study", n_samples=10)
    generated = run(p, "n-study", tmp_path).to_dataset()
    design_space = create_design_space()
    design_space.add_variable("x", lower_bound=-2.0, upper_bound=2.0)
    design_space.add_variable("y", lower_bound=-2.0, upper_bound=2.0)
    reference = create_scenario(
        [AnalyticDiscipline({"f": ROSENBROCK}, name="Rosenbrock")],
        "f",
        design_space,
        scenario_type="DOE",
        formulation_name="DisciplinaryOpt",
    )
    reference.execute(algo_name="LHS", n_samples=10, seed=1)
    assert_allclose(generated.to_numpy(), reference.to_dataset().to_numpy())


def test_rosenbrock_parametric_study_runs_every_combination(tmp_path: Path) -> None:
    dataset = run(example("rosenbrock_parametric"), "n-study", tmp_path).to_dataset()
    x, y, f = dataset.to_numpy().T
    assert len(f) == 15
    assert sorted(set(x)) == [-2.0, -1.0, 0.0, 1.0, 2.0]
    assert sorted(set(y)) == [0.0, 1.0, 2.0]
    assert_allclose(f, (1 - x) ** 2 + 100 * (y - x**2) ** 2)


def optimization(**config: Any) -> Project:
    model = component("Model", ["x"], ["obj", "cstr", "other"])
    model.config = {"expressions": {"obj": "x**2", "cstr": "x - 1", "other": "2*x"}}
    base = {
        "design_space": [{"variable": "x", "lower": [-1.0], "upper": [2.0]}],
        "objectives": [{"variable": "obj"}],
    }
    return project(driver("Opt", "optimization", model, config={**base, **config}))


def test_objective_sense_and_constraint_operators() -> None:
    source = generate(
        optimization(
            objectives=[{"variable": "obj", "sense": "maximize"}],
            constraints=[
                {
                    "variable": "cstr",
                    "operator": ">=",
                    "value": 1e-3,
                    "value_text": "1e-3",
                },
                {"variable": "other", "type": "eq", "value": 2.0},
            ],
            observables=["other"],
        ),
        "n-Opt",
    ).source
    assert "        maximize_objective=True,\n" in source
    assert "# GEMSEO constraints are 'output <= value' unless positive=True." in source
    assert '"cstr", constraint_type="ineq", positive=True, value=1e-3)' in source
    assert (
        '    scenario.add_constraint("other", constraint_type="eq", value=2.0)'
        in source
    )
    assert '    scenario.add_observable("other")' in source


def test_doe_responses_become_objective_and_observables() -> None:
    p = optimization()
    node = p.find("n-Opt")
    node.kind = "doe"  # type: ignore[union-attr]
    node.config = {  # type: ignore[union-attr]
        "design_space": [{"variable": "x", "lower": [-1.0], "upper": [2.0]}],
        "responses": ["obj", "other"],
        "algorithm": {"settings": {"n_samples": 5}},
        "execution": {"n_processes": 2},
    }
    source = generate(p, "n-Opt").source
    assert '        "obj",\n' in source
    assert '    scenario.add_observable("other")' in source
    assert 'scenario.execute(algo_name="LHS", n_samples=5, n_processes=2)' in source


def test_fast_mode_does_not_check_the_exchanged_data() -> None:
    script = generate(optimization(execution={"validate_data": False}), "n-Opt")
    assert (
        "    # Fast mode: GEMSEO does not check the data the disciplines exchange.\n"
        "    configure(validate_input_data=False, validate_output_data=False)\n"
        "    scenario = build_scenario()\n"
    ) in script.source
    assert "from gemseo import configure, configure_logger," in script.source
    assert '"validate_data": false' in script.mapping_json()
    checked = generate(optimization(), "n-Opt")
    assert "validate_input_data" not in checked.source
    assert "validate_data" not in checked.mapping_json()


def test_mixed_objective_senses_are_refused() -> None:
    with pytest.raises(CodegenError, match="minimize and maximize"):
        generate(
            optimization(
                objectives=[
                    {"variable": "obj"},
                    {"variable": "other", "sense": "maximize"},
                ]
            ),
            "n-Opt",
        )


def test_typed_values_of_design_variables_are_left_to_the_design_space() -> None:
    p = optimization()
    model = p.find("n-Model")
    model.ports[0] = model.ports[0].model_copy(  # type: ignore[union-attr]
        update={"default": 0.5, "default_text": "0.5"}
    )
    assert "default_input_data" not in generate(p, "n-Opt").source
    assert array([0.5]).shape == (1,)


def test_sellar_disciplinary_opt_optimizes_one_mda(tmp_path: Path) -> None:
    p = with_settings(example("sellar_disciplinary_opt"), "n-optimizer", max_iter=2)
    generated = run(p, "n-optimizer", tmp_path)
    mda = create_mda("MDAChain", [Sellar1(), Sellar2(), SellarSystem()])
    reference = sellar_reference("DisciplinaryOpt", disciplines=[mda])
    assert_allclose(
        generated.optimization_result.f_opt,
        reference.optimization_result.f_opt,
        rtol=1e-8,
    )


def test_optimization_on_a_surrogate_matches_hand_written_gemseo(
    tmp_path: Path,
) -> None:
    model_file = tmp_path / "Rosenbrock.pkl"
    run_folder = rosenbrock_run(tmp_path, n_samples=20)
    train(str(run_folder), ["x", "y"], ["f"], "RBFRegressor", {}, 2, str(model_file))
    p = with_settings(example("rosenbrock_surrogate"), "n-optimizer", max_iter=5)
    surrogate = p.find("n-surrogate")
    assert surrogate is not None
    surrogate.config = {"model_path": str(model_file)}  # type: ignore[union-attr]
    generated = run(p, "n-optimizer", tmp_path).optimization_result

    design_space = create_design_space()
    design_space.add_variable("x", lower_bound=-2.0, upper_bound=2.0, value=0.0)
    design_space.add_variable("y", lower_bound=-2.0, upper_bound=2.0, value=0.0)
    reference = create_scenario(
        [SurrogateDiscipline(from_pickle(model_file))],
        "f",
        design_space,
        formulation_name="DisciplinaryOpt",
    )
    reference.execute(algo_name="SLSQP", max_iter=5)
    assert_allclose(generated.x_opt, reference.optimization_result.x_opt)
    assert_allclose(generated.f_opt, reference.optimization_result.f_opt)
