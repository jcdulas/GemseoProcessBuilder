"""Training surrogates on the results of a DOE run."""

import io
from pathlib import Path

import numpy as np
import pytest
from doe_runs import points_of
from doe_runs import rosenbrock
from doe_runs import rosenbrock_run

from gemseo_process_builder.results.surrogates import seeded_settings
from gemseo_process_builder.workers.algorithms_methods import describe
from gemseo_process_builder.workers.algorithms_methods import settings_schema
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.surrogate_methods import SurrogateError
from gemseo_process_builder.workers.surrogate_methods import read_training_data
from gemseo_process_builder.workers.surrogate_methods import train
from gemseo_process_builder.workers.surrogate_methods import variables


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


def test_variables_of_a_run(tmp_path: Path) -> None:
    found = variables(str(rosenbrock_run(tmp_path)))
    assert [item["name"] for item in found["inputs"]] == ["x", "y"]
    assert found["outputs"] == [{"name": "f", "size": 1, "role": "observable"}]
    assert found["n_samples"] == 30


def test_rbf_on_rosenbrock(tmp_path: Path) -> None:
    run = rosenbrock_run(tmp_path, failed=2)
    samples = tmp_path / "surrogates" / "rbf.h5"
    result = train(str(run), ["x", "y"], ["f"], "RBFRegressor", {}, 3, str(samples))
    assert result["n_samples"] == 28  # Failed evaluations are left out.
    quality = result["quality"]["f"]
    assert quality["r2"][0] == pytest.approx(1.0)
    assert quality["rmse"][0] == pytest.approx(0.0, abs=1e-6)
    assert np.isfinite(quality["r2_cv"][0])
    assert quality["rmse_cv"][0] > 0
    points = result["points"]["f"][0]
    assert len(points["observed"]) == len(points["cross_validated"]) == 28
    assert result["inputs"][0]["name"] == "x"
    assert -2 <= result["inputs"][0]["lower"][0] < result["inputs"][0]["upper"][0] <= 2
    assert list(samples.parent.iterdir()) == [samples]  # Nothing pickled.

    from gemseo import create_surrogate

    # An RBF interpolates its training points.
    x, y = points_of(run)[5]
    discipline = create_surrogate("RBFRegressor", read_training_data(samples))
    output = discipline.execute({"x": np.array([x]), "y": np.array([y])})
    assert output["f"][0] == pytest.approx(rosenbrock(x, y))


def test_polynomial_settings(tmp_path: Path) -> None:
    run = rosenbrock_run(tmp_path)
    result = train(
        str(run),
        ["x", "y"],
        ["f"],
        "PolynomialRegressor",
        {"degree": 4},
        3,
        str(tmp_path / "p.h5"),
    )
    # The Rosenbrock function is a polynomial of degree 4.
    assert result["quality"]["f"]["r2_cv"][0] == pytest.approx(1.0)


def test_errors_are_explained(tmp_path: Path) -> None:
    run = str(rosenbrock_run(tmp_path))
    model = str(tmp_path / "m.h5")
    with pytest.raises(SurrogateError, match="no regression model named Magic"):
        train(run, ["x"], ["f"], "Magic", {}, 3, model)
    with pytest.raises(SurrogateError, match="no variable z"):
        train(run, ["z"], ["f"], "RBFRegressor", {}, 3, model)
    with pytest.raises(SurrogateError, match="at least one input"):
        train(run, [], ["f"], "RBFRegressor", {}, 3, model)
    with pytest.raises(SurrogateError, match="not valid"):
        train(run, ["x"], ["f"], "RBFRegressor", {"nothing": 1}, 3, model)


def test_regression_models_are_listed() -> None:
    names = [item["name"] for item in describe("regression")]
    assert {"RBFRegressor", "GaussianProcessRegressor", "PolynomialRegressor"} <= set(
        names
    )
    assert "RegressorChain" not in names
    assert (
        "degree" in settings_schema("regression", "PolynomialRegressor")["properties"]
    )


OFFERED = sorted(
    item["name"] for item in describe("regression") if item["name"] != "FCERegressor"
)
"""The regression models of the wizard (FCE needs a probability space)."""


@pytest.mark.parametrize("algorithm", OFFERED)
def test_each_model_is_trained_again_identically(
    tmp_path: Path, algorithm: str
) -> None:
    from gemseo import create_surrogate

    from gemseo_process_builder.workers.surrogate_methods import regression_model
    from gemseo_process_builder.workers.surrogate_methods import write_training_data

    rng = np.random.default_rng(1)
    x = rng.random((20, 2))
    samples = tmp_path / "samples.h5"
    write_training_data(samples, {"x": x}, {"f": np.sin(3 * x[:, :1]) + x[:, 1:]})
    measured = regression_model(read_training_data(samples), algorithm, {})
    measured.learn()
    # Anywhere else: create_surrogate on the same file, with the stored settings.
    settings = seeded_settings(algorithm, {})
    rebuilt = create_surrogate(algorithm, read_training_data(samples), **settings)
    point = rng.random(2)
    expected = measured.predict({"x": point[None, :]})["f"][0]
    assert rebuilt.execute({"x": point})["f"] == pytest.approx(expected, rel=1e-10)


def test_samples_are_written_exactly_in_their_order(tmp_path: Path) -> None:
    from gemseo_process_builder.workers.surrogate_methods import write_training_data

    values = {
        "z": np.array([[1 / 3], [2 / 3]]),
        "a": np.array([[0.1, 0.2], [0.3, 0.4]]),
    }
    samples = tmp_path / "samples.h5"
    write_training_data(samples, values, {"f": np.array([[1.0], [2.0]])})
    dataset = read_training_data(samples)
    assert dataset.get_columns() == ["z", "a[0]", "a[1]", "f"]
    assert np.array_equal(dataset.get_view(variable_names="z").to_numpy(), values["z"])
