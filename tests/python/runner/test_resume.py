"""Resuming a run from its caches, and the history of a killed run (SPEC § 8.8)."""

import io
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from gemseo import create_design_space
from gemseo import create_scenario
from gemseo.core.discipline import Discipline
from golden_projects import rosenbrock_doe_backup

from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.results import reader
from gemseo_process_builder.results.models import RunInfo
from gemseo_process_builder.results.models import read_info
from gemseo_process_builder.results.models import write_info
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.script_reader import read_script


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


class CrashError(Exception):
    """The machine stops in the middle of a run."""


class Sizing(Discipline):
    """``mass = (x - 0.3)²``, counting its executions; crashes after some."""

    def __init__(self, crash_after: int | None = None) -> None:
        super().__init__("Sizing")
        self.io.input_grammar.update_from_data({"x": np.zeros(1)})
        self.io.output_grammar.update_from_data({"mass": np.zeros(1)})
        self.io.input_grammar.defaults = {"x": np.zeros(1)}
        self.crash_after = crash_after
        self.executions = 0

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        if self.crash_after is not None and self.executions == self.crash_after:
            raise CrashError
        self.executions += 1
        return {"mass": (input_data["x"] - 0.3) ** 2}


def doe(sizing: Sizing, cache: Path) -> Any:
    sizing.set_cache(
        Discipline.CacheType.HDF5, hdf_file_path=cache, hdf_node_path="Study/Sizing"
    )
    space = create_design_space()
    space.add_variable("x", lower_bound=0.0, upper_bound=1.0, value=0.5)
    return create_scenario(
        [sizing], "mass", space, scenario_type="DOE", formulation_name="DisciplinaryOpt"
    )


def test_a_run_started_again_reuses_what_the_cache_holds(tmp_path: Path) -> None:
    cache = tmp_path / "study.h5"
    crashed = Sizing(crash_after=3)
    first = doe(crashed, cache)
    with pytest.raises(CrashError):
        first.execute(algo_name="LHS", n_samples=6)
    assert crashed.executions == 3
    sizing = Sizing()
    second = doe(sizing, cache)
    second.execute(algo_name="LHS", n_samples=6)
    # The three samples done come from the file: the same samples are drawn.
    assert sizing.executions == 3
    database = second.formulation.optimization_problem.database
    assert len(database) == 6
    done = first.formulation.optimization_problem.database
    for index in range(3):
        np.testing.assert_array_equal(
            done.get_x_vect(index + 1), database.get_x_vect(index + 1)
        )


def test_the_history_option_is_written_and_read_back(tmp_path: Path) -> None:
    script = tmp_path / "rosenbrock.py"
    script.write_text(generate(rosenbrock_doe_backup(), "n-study").source, "utf-8")
    read = read_script(script)
    (study,) = read["project"]["root"]["children"]
    assert study["config"]["execution"]["history_each_evaluation"] is True
    # Reading wrote no history.
    assert not (tmp_path / "history.h5").exists()


def test_the_results_of_a_killed_run_come_from_its_history(tmp_path: Path) -> None:
    folder = tmp_path / "r-1"
    folder.mkdir()
    crashed = Sizing(crash_after=4)
    scenario = doe(crashed, tmp_path / "study.h5")
    scenario.set_optimization_history_backup(
        folder / "history.h5", at_each_function_call=True, erase=True
    )
    with pytest.raises(CrashError):  # Killed: nothing saved at the end.
        scenario.execute(algo_name="LHS", n_samples=6)
    info = RunInfo(
        id="r-1", driver="n-study", driver_name="Study", status="killed", created="t"
    )
    write_info(folder, info)
    shutil.copyfile(
        Path(__file__).parent / "map_doe.json", folder / "script.gpb-map.json"
    )
    table = reader.load(folder)
    assert len(table.values) == 4
    recovered = read_info(folder)
    assert recovered is not None
    assert [(v.name, v.role) for v in recovered.variables] == [
        ("x", "design variable"),
        ("mass", "output"),
    ]
    assert recovered.summary.n_evaluations == 4
    assert (folder / "dataset.npy").is_file()
