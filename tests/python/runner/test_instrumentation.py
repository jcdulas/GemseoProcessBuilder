"""Instrumentation of a real GEMSEO scenario, in-process."""

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from gemseo import configure
from golden_projects import example

from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.runner.instrumentation import ProblemListener
from gemseo_process_builder.runner.instrumentation import observe_disciplines
from gemseo_process_builder.runner.instrumentation import observe_nested_scenarios
from gemseo_process_builder.runner.instrumentation import top_disciplines
from gemseo_process_builder.runner.rate_limiter import RateLimiter
from gemseo_process_builder.runner.stop import RunStopped
from gemseo_process_builder.runner.stop import StopFlag


@pytest.fixture
def discipline_status() -> Iterator[None]:
    configure(enable_discipline_status=True)
    yield
    configure(enable_discipline_status=False)


def sellar(tmp_path: Path, max_iter: int) -> tuple[Any, Any, dict[str, Any]]:
    p = example("sellar_mdf")
    p.find("n-optimizer").config["algorithm"]["settings"]["max_iter"] = max_iter  # type: ignore[union-attr]
    script = generate(p, "n-optimizer")
    path = tmp_path / "script.py"
    path.write_text(script.source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("sellar_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, module.build_scenario(), script.mapping


def instrument(
    scenario: Any, mapping: dict[str, Any], stop: StopFlag
) -> tuple[list[tuple[str, Any]], ProblemListener]:
    events: list[tuple[str, Any]] = []
    limiter = RateLimiter(lambda *event: events.append(event), limit=100_000)
    problem = scenario.formulation.optimization_problem
    listener = ProblemListener(problem, limiter, stop, "iteration", 3)
    observe_disciplines(scenario.disciplines, mapping, limiter, stop)
    return events, listener


@pytest.mark.usefixtures("discipline_status")
def test_iterations_and_states_of_sellar(tmp_path: Path) -> None:
    module, scenario, mapping = sellar(tmp_path, max_iter=3)
    events, listener = instrument(scenario, mapping, StopFlag())
    module.execute_scenario(scenario)
    listener.report_pending()
    iterations = [payload for name, payload in events if name == "iteration"]
    assert [item["index"] for item in iterations] == [1, 2, 3]
    first = iterations[0]
    assert first["x"]["x_1"] == 1.0
    assert first["x"]["x_shared"] == pytest.approx([4.0, 3.0])
    assert set(first["g"]) == {"c_1", "c_2"}
    assert first["feasible"] is True
    states = [payload for name, payload in events if name == "status"]
    assert {state["node_id"] for state in states} == {
        "n-sellar1",
        "n-sellar2",
        "n-sellarsystem",
    }
    assert {state["state"] for state in states} == {"pending", "running", "done"}
    progress = [payload for name, payload in events if name == "progress"]
    assert progress[-1] == {"current": 3, "total": 3, "unit": "iteration"}


@pytest.mark.usefixtures("discipline_status")
def test_stop_goes_through_gemseo(tmp_path: Path) -> None:
    module, scenario, mapping = sellar(tmp_path, max_iter=50)
    stop = StopFlag()
    instrument(scenario, mapping, stop)
    stop.set()
    with pytest.raises(RunStopped):
        module.execute_scenario(scenario)


def doe_around_optimization(tmp_path: Path) -> tuple[Any, Any, dict[str, Any]]:
    p = example("doe_around_optimization")
    p.find("n-study").config["algorithm"]["settings"]["n_samples"] = 2  # type: ignore[union-attr]
    p.find("n-optimizer").config["algorithm"]["settings"]["max_iter"] = 3  # type: ignore[union-attr]
    script = generate(p, "n-study")
    path = tmp_path / "script.py"
    path.write_text(script.source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("nested_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, module.build_scenario(), script.mapping


@pytest.mark.usefixtures("discipline_status")
def test_nested_scenarios_report_states_and_inner_progress(tmp_path: Path) -> None:
    module, scenario, mapping = doe_around_optimization(tmp_path)
    events: list[tuple[str, Any]] = []
    limiter = RateLimiter(lambda *event: events.append(event), limit=100_000)
    disciplines = top_disciplines(scenario)
    observe_disciplines(disciplines, mapping, limiter, StopFlag())
    assert observe_nested_scenarios(disciplines, mapping, limiter, StopFlag()) == [
        "n-optimizer"
    ]
    module.execute_scenario(scenario)
    states = {payload["node_id"] for name, payload in events if name == "status"}
    # The disciplines inside the optimization, and the optimization itself.
    assert states == {"n-sellar1", "n-sellar2", "n-sellarsystem", "n-optimizer"}
    inner = [payload for name, payload in events if name == "inner_progress"]
    assert [item["current"] for item in inner] == [1, 2, 3, 1, 2, 3]
    assert inner[0]["name"] == "Optimizer"


def test_parallel_samples_report_the_processes() -> None:
    events: list[tuple[str, Any]] = []
    limiter = RateLimiter(lambda *event: events.append(event), limit=100_000)

    class Problem:
        database = type("Database", (), {"add_new_iter_listener": lambda *a: None})()

    listener = ProblemListener(Problem(), limiter, StopFlag(), "sample", 4, processes=2)
    listener.index = 0
    listener._values = lambda x: {}  # type: ignore[method-assign]
    listener._inputs = lambda x: {}  # type: ignore[method-assign]
    listener.new_point([0.0])
    listener.report_pending()
    progress = [payload for name, payload in events if name == "progress"]
    assert progress == [{"current": 1, "total": 4, "unit": "sample", "processes": 2}]


@pytest.mark.usefixtures("discipline_status")
def test_bilevel_sub_scenarios_are_followed(tmp_path: Path) -> None:
    # BiLevel copies the sub-scenario databases, listeners included.
    p = example("sobieski_bilevel")
    p.find("n-system").config["algorithm"]["settings"]["max_iter"] = 1  # type: ignore[union-attr]
    for name in ("propulsion", "aerodynamics", "structure"):
        node = p.find(f"n-{name}-optimizer")
        node.config["algorithm"]["settings"]["max_iter"] = 2  # type: ignore[union-attr]
    script = generate(p, "n-system")
    path = tmp_path / "script.py"
    path.write_text(script.source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("bilevel_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scenario = module.build_scenario()
    events: list[tuple[str, Any]] = []
    limiter = RateLimiter(lambda *event: events.append(event), limit=100_000)
    disciplines = top_disciplines(scenario)
    observe_disciplines(disciplines, script.mapping, limiter, StopFlag())
    observe_nested_scenarios(disciplines, script.mapping, limiter, StopFlag())
    module.execute_scenario(scenario)
    states = {payload["node_id"] for name, payload in events if name == "status"}
    assert {"n-structure", "n-structure-optimizer", "n-mission"} <= states
    inner = {payload["node_id"] for name, payload in events if name == "inner_progress"}
    assert inner == {
        "n-propulsion-optimizer",
        "n-aerodynamics-optimizer",
        "n-structure-optimizer",
    }


def test_the_fast_mode_turns_off_the_checks_of_gemseo() -> None:
    from gemseo.utils.global_configuration import _configuration

    from gemseo_process_builder.runner.__main__ import prepare_gemseo

    try:
        prepare_gemseo(validate_data=False)
        assert not _configuration.validate_input_data
        assert not _configuration.validate_output_data
        assert _configuration.enable_discipline_status
        prepare_gemseo()
        assert _configuration.validate_input_data
    finally:
        configure()
