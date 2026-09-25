import json
from pathlib import Path

import numpy as np

from gemseo_process_builder.results import reader
from gemseo_process_builder.results.reader import bin_counts

CASE = Path(__file__).parents[2] / "js" / "fixtures" / "binning_case.json"
SELLAR_RUN = Path(__file__).parent / "fixtures" / "sellar_run"


def array(values: list[float | None]) -> np.ndarray:
    return np.array([np.nan if value is None else value for value in values])


def test_worker_binning_matches_the_shared_case() -> None:
    case = json.loads(CASE.read_text(encoding="utf-8"))
    result = bin_counts(array(case["x"]), array(case["y"]), case["bins"])
    assert result == case["expected"]


def test_identical_values_and_single_point() -> None:
    result = bin_counts(np.array([2.0, 2.0]), np.array([5.0, 5.0]), 2)
    assert (result["x"], result["y"]) == ([1.5, 2.5], [4.5, 5.5])
    assert result["counts"] == [[0, 0], [0, 2]]


def test_binned_and_matrix_of_a_run() -> None:
    binned = reader.binned(SELLAR_RUN, "x_shared[0]", "obj", bins=2)
    assert sum(map(sum, binned["counts"])) == 3
    matrix = reader.matrix(SELLAR_RUN, ["obj"], max_rows=2)
    assert matrix["total"] == 3
    assert matrix["evaluations"] == [1.0, 3.0]
    assert len(matrix["columns"]["obj"]) == 2


def test_rows_of_a_selection() -> None:
    page = reader.rows(SELLAR_RUN, evaluations=[1, 3])
    assert [row[0] for row in page["rows"]] == [1.0, 3.0]
