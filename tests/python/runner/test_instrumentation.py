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
