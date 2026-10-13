"""The pattern of the architecture study, with fakes (SPEC § 15.3, plan 79).

A parametric study over a requested count; a planner snaps it to a viable one,
a producer and a sizing cached in a file. Two requests that snap to one
architecture are produced and sized once, and a run started again on the same
file computes nothing.
"""

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from builders import component
from builders import driver
from builders import project

from gemseo_process_builder.codegen.generator import generate

FAKES = (
    Path(__file__).parents[1] / "fixtures" / "architecture_pattern" / "outer_loop.py"
)

pytestmark = pytest.mark.usefixtures("in_process_caches")


@pytest.fixture(autouse=True)
def restored_imports(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The script imports the fakes from their folder, put on ``sys.path``."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    yield
    sys.modules.pop("outer_loop", None)


def study(cache: Path) -> Any:
    def fake(name: str, ins: list[str], outs: list[str], cached: bool) -> Any:
        config: dict[str, Any] = {"module_path": str(FAKES), "function": name}
        if cached:
            config["cache"] = {"type": "hdf5", "file": str(cache), "node": name}
        return component(name, ins, outs, kind="python_function", config=config)

    planner = fake("planner", ["stringers"], ["obtained"], cached=False)
    producer = fake("producer", ["obtained"], ["initial_mass"], cached=True)
    sizing = fake("sizing", ["initial_mass", "obtained"], ["mass"], cached=True)
    levels = [{"variable": "stringers", "mode": "list", "values": [3, 4, 5, 6]}]
    return project(
        driver(
            "Study",
            "parametric",
            planner,
            producer,
            sizing,
            config={"levels": levels, "responses": ["mass", "obtained"]},
        )
    )


def run(source: str) -> Any:
    namespace: dict[str, Any] = {"__name__": "architecture_pattern_study"}
    exec(compile(source, "architecture_pattern_study.py", "exec"), namespace)
    scenario = namespace["build_scenario"]()
    namespace["execute_scenario"](scenario)
    return scenario


def test_requests_snapping_to_one_architecture_are_sized_once(tmp_path: Path) -> None:
    cache = tmp_path / "caches" / "study.h5"
    source = generate(study(cache), "n-Study").source
    assert source.count(".set_cache(") == 2
    first = run(source)
    calls = sys.modules["outer_loop"].CALLS
    # 3 and 4 snap to 4, 5 and 6 to 6: two architectures.
    assert calls == {"producer": 2, "sizing": 2}
    dataset = first.to_dataset()
    assert sorted(dataset.get_view(variable_names="obtained").to_numpy().ravel()) == [
        4.0,
        4.0,
        6.0,
        6.0,
    ]
    # A run started again on the same file computes nothing.
    calls.update(producer=0, sizing=0)
    run(source)
    assert calls == {"producer": 0, "sizing": 0}
