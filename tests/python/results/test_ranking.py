"""Ranking the variables of a run: sensitivity, gradients and active set."""

import shutil
from pathlib import Path

import numpy as np
import pytest

from gemseo_process_builder.results import reader
from gemseo_process_builder.results.models import RunInfo
from gemseo_process_builder.results.models import VariableInfo
from gemseo_process_builder.results.models import write_info
from gemseo_process_builder.results.ranking import ranking
from gemseo_process_builder.results.reader import ResultsError

SELLAR_RUN = Path(__file__).parent / "fixtures" / "sellar_run"


def optimization_run(folder: Path, binary: bool = True) -> Path:
    """A run of 3 design variables x in [0, 1]³, an objective f and 2 constraints g.

    f depends mostly on x[0]; the last evaluation is the best: x[0] at its lower
    bound, g[0] at its limit (active) and g[1] satisfied.
    """
    run = folder / "r-opt"
    run.mkdir(parents=True)
    x = np.random.default_rng(5).uniform(0.2, 1.0, (40, 3))
    x[-1] = [0.0, 0.5, 0.5]
    f = 3 * x[:, 0] + 0.1 * x[:, 1]
    g = np.column_stack([0.1 - x[:, 0] - 0.1 * x[:, 2] + 0.05, -np.ones(40)])
    g[-1, 0] = 0.0
    values = np.column_stack([x, f, g])
    header = [
        "GROUP" + ",parameters" * 6,
        "VARIABLE,x,x,x,f,g,g",
        "COMPONENT,0,1,2,0,0,1",
    ]
    rows = (
        []
        if binary
        else [
            f"{i}," + ",".join(str(float(value)) for value in row)
            for i, row in enumerate(values)
        ]
    )
    (run / "dataset.csv").write_text("\n".join(header + rows) + "\n", encoding="utf-8")
    if binary:
        np.save(run / "dataset.npy", np.asfortranarray(values))
    write_info(
        run,
        RunInfo(
            id="r-opt",
            driver="n-optimizer",
            driver_name="Optimizer",
            status="completed",
            created="2026-09-25T10:00:00",
            variables=[
                VariableInfo(
                    name="x",
                    size=3,
                    role="design variable",
                    lower=[0.0] * 3,
                    upper=[1.0] * 3,
                ),
                VariableInfo(name="f", role="objective"),
                VariableInfo(
                    name="g", size=2, role="constraint", constraint_type="ineq"
                ),
            ],
        ),
    )
    return run


def test_binary_values_and_text_values_agree(tmp_path: Path) -> None:
    binary = reader.load(optimization_run(tmp_path / "a"))
    text = reader.load(optimization_run(tmp_path / "b", binary=False))
    assert [c.name for c in binary.columns] == [c.name for c in text.columns]
    np.testing.assert_allclose(binary.values, text.values)
    assert binary.values.flags.f_contiguous  # Read column by column.


def test_best_evaluation_and_columns_by_name(tmp_path: Path) -> None:
    table = reader.load(optimization_run(tmp_path))
    assert reader.best_position(table) == 39
    assert table.index_of("g[1]") == 6
    with pytest.raises(ResultsError, match="no column"):
        table.index_of("h")


def test_rows_of_some_columns(tmp_path: Path) -> None:
    page = reader.rows(optimization_run(tmp_path), limit=2, names=["f", "x[0]"])
    assert page["columns"] == ["f", "x[0]"]
    assert page["rows"][0][0] == pytest.approx(3 * page["rows"][0][1], abs=0.11)


def test_ranking_by_sensitivity(tmp_path: Path) -> None:
    result = ranking(optimization_run(tmp_path), "sensitivity", limit=2)
    assert len(result["inputs"]) == 2
    assert result["inputs"][0]["name"] == "x[0]"
    assert result["inputs"][0]["score"] > 0.9
    assert (result["response"], result["evaluation"], result["total_inputs"]) == (
        "f",
        40,
        3,
    )


def test_active_set(tmp_path: Path) -> None:
    run = optimization_run(tmp_path)
    result = ranking(run, "active")
    assert result["inputs"][0] == {"name": "x[0]", "score": 1.0, "bound": "lower"}
    assert result["at_bounds"] == 1
    statuses = {item["name"]: item["status"] for item in result["responses"]}
    assert statuses == {"f": None, "g[0]": "active", "g[1]": "satisfied"}
    active = ranking(run, "active", active_only=True)
    assert [item["name"] for item in active["responses"]] == ["f", "g[0]"]


def test_ranking_by_gradient(tmp_path: Path) -> None:
    # The gradients of Sellar's objective at the optimum, times the ranges.
    result = ranking(SELLAR_RUN, "gradient")
    assert result["inputs"][0]["name"] == "x_shared[0]"
    assert result["note"] == ""
    with pytest.raises(ResultsError, match="no history"):
        ranking(optimization_run(tmp_path), "gradient")


def test_gradients_of_chosen_variables(tmp_path: Path) -> None:
    run = tmp_path / "sellar"
    shutil.copytree(SELLAR_RUN, run)
    full = reader.gradients(run)["functions"][0]["last"][0]
    # In the order asked for: the most important first.
    result = reader.gradients(run, inputs=["x_shared[1]", "x_1"], functions=["obj"])
    assert result["labels"] == ["x_shared[1]", "x_1"]
    (objective,) = result["functions"]
    assert objective["last"][0] == [full[3], full[0]]
