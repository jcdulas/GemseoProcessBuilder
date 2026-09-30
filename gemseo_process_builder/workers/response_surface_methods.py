"""Response surfaces of a run: ``results.ranking`` and ``results.response_surface``.

A response surface shows the landscape of the design space around the best
evaluation: a GEMSEO regression model (Kriging, a neural network…) is trained
on the evaluations of a run, then predicts the responses on a grid of two
design variables, the others staying at their best values (SPEC § 12.2).
Only the variables that matter are used, whatever the size of the run: the
page chooses them with the ranking.
"""

import time
from pathlib import Path
from typing import Any

import numpy as np

from gemseo_process_builder.results import ranking
from gemseo_process_builder.results.reader import ResultsError
from gemseo_process_builder.results.reader import RunTable
from gemseo_process_builder.results.reader import best_position
from gemseo_process_builder.results.reader import load
from gemseo_process_builder.workers.gemseo_loader import require_gemseo
from gemseo_process_builder.workers.server import RequestContext
from gemseo_process_builder.workers.server import WorkerError
from gemseo_process_builder.workers.surrogate_methods import SurrogateError
from gemseo_process_builder.workers.surrogate_methods import r2_scores
from gemseo_process_builder.workers.surrogate_methods import regression_model

ALGORITHMS: dict[str, tuple[str, dict[str, Any]]] = {
    # Two restarts instead of GEMSEO's ten: four times faster, as good on the
    # tests (without restart, the length scales often stay wrong).
    "GaussianProcessRegressor": (
        "Kriging (Gaussian process)",
        {"n_restarts_optimizer": 2},
    ),
    "MLPRegressor": (
        "Neural network (multilayer perceptron)",
        {"hidden_layer_sizes": (32, 32)},
    ),
    "RBFRegressor": ("Radial basis functions", {}),
    "PolynomialRegressor": ("Quadratic polynomial", {"degree": 2}),
}
"""The metamodels offered, with their labels and settings."""

MAX_INPUTS = 20
"""The model is trained on these design variables at most."""

MAX_OUTPUTS = 12
MAX_GRID = 80
TEST_SHARE = 0.2
"""The share of the evaluations kept aside to measure the quality."""


def _rows(table: RunTable, used: list[int], max_rows: int) -> np.ndarray:
    """The complete evaluations, evenly spaced beyond ``max_rows``."""
    complete = np.flatnonzero(np.isfinite(table.values[:, used]).all(axis=1))
    if len(complete) > max_rows:
        spaced = np.linspace(0, len(complete) - 1, max_rows).round().astype(int)
        complete = complete[np.unique(spaced)]
    return complete


def _axis(table: RunTable, position: int, rows: np.ndarray, size: int) -> np.ndarray:
    """The grid of a variable: between its bounds, or its values without bounds."""
    lower, upper = ranking.column_bounds(table, [position])
    low, high = float(lower[0]), float(upper[0])
    if not (np.isfinite(low) and np.isfinite(high) and high > low):
        values = table.values[rows, position]
        low, high = float(values.min()), float(values.max())
    if high <= low:
        low, high = low - 0.5, high + 0.5
    return np.linspace(low, high, size)


def _plain(values: np.ndarray) -> list[Any]:
    return [None if not np.isfinite(value) else float(value) for value in values]


def response_surface(
    folder: Path,
    x: str,
    y: str,
    outputs: list[str],
    inputs: list[str] | None = None,
    algorithm: str = "GaussianProcessRegressor",
    grid: int = 40,
    max_rows: int = 1000,
    seed: int = 1,
) -> dict[str, Any]:
    """Predict responses on a grid of two design variables.

    Args:
        folder: The run folder.
        x: The design variable along the horizontal axis.
        y: The design variable along the vertical axis.
        outputs: The responses to predict (objective, constraints…).
        inputs: The design variables the model learns from, besides ``x`` and
            ``y``: the others stay at their values at the best evaluation.
        algorithm: A key of ``ALGORITHMS``.
        grid: The number of values along each axis.
        max_rows: The evaluations used at most, evenly spaced.
        seed: The seed splitting the training and test evaluations.

    Returns:
        The grid values of ``x`` and ``y``; per output, the predictions
        ``z[j][i]`` at ``(x[i], y[j])`` and the quality of the model; the
        training evaluations, and the best one.
    """
    require_gemseo()
    from gemseo.datasets.io_dataset import IODataset

    if algorithm not in ALGORITHMS:
        msg = f"Unknown metamodel {algorithm}."
        raise ResultsError(msg)
    if x == y:
        msg = "Choose two different variables."
        raise ResultsError(msg)
    if not outputs:
        msg = "Choose at least one response."
        raise ResultsError(msg)
    start = time.perf_counter()
    table = load(folder)
    best = best_position(table)
    if best is None:
        msg = "The run has no evaluations."
        raise ResultsError(msg)
    names = [x, y] + [
        name for name in dict.fromkeys(inputs or []) if name not in (x, y)
    ]
    names = names[:MAX_INPUTS]
    outputs = list(dict.fromkeys(outputs))[:MAX_OUTPUTS]
    input_positions = [table.index_of(name) for name in names]
    output_positions = [table.index_of(name) for name in outputs]
    for name, position in zip(names, input_positions, strict=True):
        if table.columns[position].role != "design variable":
            msg = f"{name} is not a design variable."
            raise ResultsError(msg)
    rows = _rows(table, input_positions + output_positions, max_rows)
    if len(rows) < 5:
        msg = f"The run has {len(rows)} complete evaluations: at least 5 are needed."
        raise ResultsError(msg)

    label, settings = ALGORITHMS[algorithm]
    order = np.random.default_rng(seed).permutation(len(rows))
    test = np.sort(order[: max(1, int(len(rows) * TEST_SHARE))])
    training = np.setdiff1d(np.arange(len(rows)), test)
    size = max(5, min(grid, MAX_GRID))
    xs = _axis(table, input_positions[0], rows, size)
    ys = _axis(table, input_positions[1], rows, size)
    grid_x, grid_y = np.meshgrid(xs, ys)
    points = {"x0": grid_x.reshape(-1, 1), "x1": grid_y.reshape(-1, 1)}
    for index, position in enumerate(input_positions[2:], start=2):
        points[f"x{index}"] = np.full((size * size, 1), table.values[best, position])
    tested = {
        f"x{index}": table.values[rows[test], position][:, None]
        for index, position in enumerate(input_positions)
    }

    # One model per response: a response with outliers would spoil the
    # others if they shared the settings of one model (the length scales of
    # Kriging). Each input column is a scalar variable: a vector of a thousand
    # elements can be learned from a few of them.
    predictions = []
    for position in output_positions:
        dataset = IODataset()
        for index, input_position in enumerate(input_positions):
            values = table.values[rows, input_position][:, None]
            dataset.add_input_variable(f"x{index}", values)
        dataset.add_output_variable("y", table.values[rows, position][:, None])
        try:
            # The quality on evaluations the model did not learn from, then
            # the model learned from all of them.
            checked = regression_model(dataset, algorithm, settings)
            checked.learn(samples=training.tolist())
            observed = table.values[rows[test], position][:, None]
            quality = r2_scores(observed, checked.predict(tested)["y"])[0]
            model = regression_model(dataset, algorithm, settings)
            model.learn()
        except SurrogateError as error:
            raise ResultsError(str(error)) from None
        predictions.append((quality, model.predict(points)["y"].reshape(size, size)))

    feasible = table.by_role("feasibility")
    return {
        "algorithm": algorithm,
        "label": label,
        "inputs": names,
        "x": {"name": x, "values": xs.tolist()},
        "y": {"name": y, "values": ys.tolist()},
        "outputs": [
            {
                "name": name,
                "role": table.columns[position].role,
                "z": [_plain(row) for row in surface],
                "r2": quality if np.isfinite(quality) else None,
                "samples": _plain(table.values[rows, position]),
            }
            for name, position, (quality, surface) in zip(
                outputs, output_positions, predictions, strict=True
            )
        ],
        "samples": {
            "evaluations": (rows + 1).tolist(),
            "x": _plain(table.values[rows, input_positions[0]]),
            "y": _plain(table.values[rows, input_positions[1]]),
            "feasible": _plain(table.values[rows, feasible[0]]) if feasible else None,
        },
        "best": {
            "evaluation": best + 1,
            "x": float(table.values[best, input_positions[0]]),
            "y": float(table.values[best, input_positions[1]]),
        },
        "n_rows": len(rows),
        "n_test": len(test),
        "seconds": round(time.perf_counter() - start, 2),
    }


def _reporting(function: Any) -> Any:
    def method(params: dict[str, Any], context: RequestContext) -> Any:
        try:
            return function(params)
        except ResultsError as error:
            raise WorkerError("results_error", str(error)) from None

    return method


def _ranking(params: dict[str, Any]) -> dict[str, Any]:
    method = str(params.get("method", "sensitivity"))
    if method not in ("sensitivity", "gradient", "active"):
        raise WorkerError("invalid_params", f"Unknown ranking {method}.")
    return ranking.ranking(
        Path(str(params["folder"])),
        method,  # type: ignore[arg-type]
        str(params.get("response") or ""),
        int(params.get("limit", 50)),
        bool(params.get("active_only", False)),
        int(params.get("response_limit", 500)),
    )


def _surface(params: dict[str, Any]) -> dict[str, Any]:
    return response_surface(
        Path(str(params["folder"])),
        str(params["x"]),
        str(params["y"]),
        [str(name) for name in params.get("outputs") or []],
        [str(name) for name in params.get("inputs") or []],
        str(params.get("algorithm", "GaussianProcessRegressor")),
        int(params.get("grid", 40)),
        int(params.get("max_rows", 1000)),
    )


def algorithms() -> list[dict[str, str]]:
    """The metamodels offered, for the page."""
    return [{"name": name, "label": label} for name, (label, _) in ALGORITHMS.items()]


def register(server: Any) -> None:
    """Add the ranking and response surface methods to the worker."""
    server.add("results.ranking", _reporting(_ranking))
    server.add("results.response_surface", _reporting(_surface))
    server.add("results.surface_algorithms", lambda params, context: algorithms())
