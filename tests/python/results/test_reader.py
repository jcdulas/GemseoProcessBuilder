import csv
import shutil
from pathlib import Path

import pytest

from gemseo_process_builder.results import reader
from gemseo_process_builder.results.reader import Filter
from gemseo_process_builder.results.reader import ResultsError
from gemseo_process_builder.results.reader import Sort

SELLAR_RUN = Path(__file__).parent / "fixtures" / "sellar_run"


def test_columns_and_roles() -> None:
    columns = {column["name"]: column["role"] for column in reader.columns(SELLAR_RUN)}
    assert columns == {
        "evaluation": "index",
        "x_1": "design variable",
        "x_2": "design variable",
        "x_shared[0]": "design variable",
        "x_shared[1]": "design variable",
        "c_1": "constraint",
        "c_2": "constraint",
        "obj": "objective",
        "feasible": "feasibility",
    }


def test_summary() -> None:
    summary = reader.summary(SELLAR_RUN)
    assert (summary["rows"], summary["status"]) == (3, "completed")
    assert summary["summary"]["best_objective"] == pytest.approx(3.4106339)


def test_pages() -> None:
    page = reader.rows(SELLAR_RUN, offset=1, limit=1)
    assert page["total"] == 3
    (row,) = page["rows"]
    assert row[0] == 2.0  # The second evaluation.
    assert row[page["columns"].index("obj")] == pytest.approx(5.39166)
    assert row[-1] == 1.0  # Feasible.


def test_sort_and_filters() -> None:
    by_objective = reader.rows(SELLAR_RUN, sort=Sort(column="obj"))
    assert [row[0] for row in by_objective["rows"]] == [3.0, 2.0, 1.0]
    descending = reader.rows(SELLAR_RUN, sort=Sort(column="obj", descending=True))
    assert [row[0] for row in descending["rows"]] == [1.0, 2.0, 3.0]
    filtered = reader.rows(
        SELLAR_RUN,
        filters=[
            Filter(column="obj", op="<", value=10),
            Filter(column="x_shared[0]", op="between", value=(2.0, 2.3)),
        ],
    )
    assert [row[0] for row in filtered["rows"]] == [3.0]


def test_history() -> None:
    history = reader.history(SELLAR_RUN, ["obj"])
    assert history["evaluation"] == [1.0, 2.0, 3.0]
    assert history["values"]["obj"][0] == pytest.approx(22.952626)


def test_unknown_column() -> None:
    with pytest.raises(ResultsError, match="no column nope"):
        reader.history(SELLAR_RUN, ["nope"])


def test_export_csv(tmp_path: Path) -> None:
    path = tmp_path / "export.csv"
    count = reader.export_csv(
        SELLAR_RUN, path, ["evaluation", "obj"], sort=Sort(column="obj")
    )
    assert count == 3
    with path.open(encoding="utf-8", newline="") as file:
        rows = list(csv.reader(file))
    assert rows[0] == ["evaluation", "obj"]
    assert rows[1][0] == "3.0"


def test_missing_results(tmp_path: Path) -> None:
    shutil.copy(SELLAR_RUN / "run.json", tmp_path / "run.json")
    with pytest.raises(ResultsError, match="has no results"):
        reader.summary(tmp_path)
    with pytest.raises(ResultsError, match="is not a run folder"):
        reader.summary(tmp_path / "nothing")


def test_gradients_of_the_objective_and_constraints_by_iteration() -> None:
    result = reader.gradients(SELLAR_RUN)
    assert result["labels"] == ["x_1", "x_2", "x_shared[0]", "x_shared[1]"]
    functions = {item["name"]: item for item in result["functions"]}
    assert set(functions) == {"obj", "c_1", "c_2"}
    objective = functions["obj"]
    assert objective["role"] == "objective"
    assert objective["iterations"] == [1, 2, 3]
    assert len(objective["last"][0]) == 4
    assert objective["norms"][-1] > 0
