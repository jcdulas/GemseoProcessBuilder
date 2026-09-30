"""Response surfaces predicted by metamodels trained on a run."""

import io
from pathlib import Path

import pytest
from doe_runs import points_of
from doe_runs import rosenbrock_run

from gemseo_process_builder.results.reader import ResultsError
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.response_surface_methods import algorithms
from gemseo_process_builder.workers.response_surface_methods import response_surface


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


def test_quadratic_surface_of_rosenbrock(tmp_path: Path) -> None:
    run = rosenbrock_run(tmp_path, n_samples=40, failed=2)
    result = response_surface(
        run, "x", "y", ["f"], algorithm="PolynomialRegressor", grid=12
    )
    assert result["x"]["values"][0] == -2.0  # The grid spans the bounds.
    assert result["y"]["values"][-1] == 2.0
    (output,) = result["outputs"]
    assert (len(output["z"]), len(output["z"][0])) == (12, 12)
    assert output["role"] == "observable"
    assert -1.0 < output["r2"] <= 1.0
    assert (result["n_rows"], result["n_test"]) == (38, 7)
    assert len(result["samples"]["x"]) == len(output["samples"]) == 38
    assert result["samples"]["feasible"] is None


def test_kriging_on_swapped_axes(tmp_path: Path) -> None:
    run = rosenbrock_run(tmp_path, n_samples=30)
    result = response_surface(run, "y", "x", ["f"], grid=6)
    assert result["label"].startswith("Kriging")
    assert result["x"]["name"] == "y"
    assert result["samples"]["x"][0] == pytest.approx(points_of(run)[0][1])
    # Kriging interpolates: the prediction at a corner lies within the values.
    corner = result["outputs"][0]["z"][0][0]
    assert 0 <= corner < 5000


def test_invalid_requests(tmp_path: Path) -> None:
    run = rosenbrock_run(tmp_path)
    with pytest.raises(ResultsError, match="two different"):
        response_surface(run, "x", "x", ["f"])
    with pytest.raises(ResultsError, match="not a design variable"):
        response_surface(run, "x", "f", ["f"])
    with pytest.raises(ResultsError, match="Unknown metamodel"):
        response_surface(run, "x", "y", ["f"], algorithm="Oracle")
    assert [item["name"] for item in algorithms()][:2] == [
        "GaussianProcessRegressor",
        "MLPRegressor",
    ]
