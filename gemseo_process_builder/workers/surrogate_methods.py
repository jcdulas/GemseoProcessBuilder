"""Surrogate models trained on the results of a run (runs in the worker; SPEC § 7.4).

A surrogate is a GEMSEO regression model trained on the evaluations of a DOE
run: its inputs are variables varied by the DOE, its outputs the responses.
Its quality is measured on the training data and by k-fold cross-validation:
each fold is predicted by a model trained on the other folds.

The trained model is pickled here; pickles are never loaded in the UI process.
"""

from pathlib import Path
from typing import Any

import numpy as np

from gemseo_process_builder.results.reader import ResultsError
from gemseo_process_builder.results.reader import RunTable
from gemseo_process_builder.results.reader import load
from gemseo_process_builder.workers.gemseo_loader import require_gemseo
from gemseo_process_builder.workers.server import RequestContext
from gemseo_process_builder.workers.server import WorkerError

TRANSFORMER = {"inputs": "MinMaxScaler", "outputs": "MinMaxScaler"}
"""Variables are scaled to [0, 1] for learning, like SurrogateDiscipline does."""

MAX_POINTS = 5000
"""Points of the predicted-vs-observed charts, at most."""

INPUT_ROLES = ("design variable",)


class SurrogateError(WorkerError):
    """A surrogate that cannot be trained; the message is for the user."""

    def __init__(self, message: str) -> None:
        super().__init__("surrogate_error", message)


def _table(folder: str) -> RunTable:
    try:
        return load(Path(folder))
    except ResultsError as error:
        raise SurrogateError(str(error)) from None


def variables(folder: str) -> dict[str, Any]:
    """The variables a surrogate of a run can use, and the number of samples.

    Returns:
        ``inputs`` (the design variables) and ``outputs`` (the other variables),
        each as ``[{"name", "size", "role"}]``, and ``n_samples``.
    """
    table = _table(folder)
    sizes: dict[str, int] = {}
    for column in table.columns:
        if column.role not in ("index", "feasibility"):
            sizes[column.variable] = sizes.get(column.variable, 0) + 1
    roles = {column.variable: column.role for column in table.columns}
    described = [
        {"name": name, "size": size, "role": roles[name]}
        for name, size in sizes.items()
    ]
    return {
        "inputs": [item for item in described if item["role"] in INPUT_ROLES],
        "outputs": [item for item in described if item["role"] not in INPUT_ROLES],
        "n_samples": len(table.values),
    }


def _columns(table: RunTable, names: list[str]) -> dict[str, list[int]]:
    """The positions of the columns of each variable, in component order."""
    positions: dict[str, list[int]] = {}
    for name in names:
        found = [
            (column.component, index)
            for index, column in enumerate(table.columns)
            if column.variable == name
        ]
        if not found:
            msg = f"The run has no variable {name}."
            raise SurrogateError(msg)
        positions[name] = [index for _, index in sorted(found)]
    return positions


def training_data(
    folder: str, inputs: list[str], outputs: list[str]
) -> tuple[Any, dict[str, np.ndarray], dict[str, np.ndarray]]:
    """The training dataset of a run, without the failed evaluations.

    Returns:
        The ``IODataset``, and the input and output values by name.
    """
    from gemseo.datasets.io_dataset import IODataset

    if not inputs or not outputs:
        msg = "Choose at least one input and one output."
        raise SurrogateError(msg)
    table = _table(folder)
    positions = _columns(table, inputs + outputs)
    used = [index for name in inputs + outputs for index in positions[name]]
    rows = table.values[~np.isnan(table.values[:, used]).any(axis=1)]
    if len(rows) < 3:
        msg = f"The run has {len(rows)} complete evaluations: at least 3 are needed."
        raise SurrogateError(msg)
    input_values = {name: rows[:, positions[name]] for name in inputs}
    output_values = {name: rows[:, positions[name]] for name in outputs}
    dataset = IODataset()
    for name, values in input_values.items():
        dataset.add_input_variable(name, values)
    for name, values in output_values.items():
        dataset.add_output_variable(name, values)
    return dataset, input_values, output_values


def regression_model(dataset: Any, algorithm: str, settings: dict[str, Any]) -> Any:
    """A GEMSEO regression model of a dataset, its inputs and outputs scaled."""
    from gemseo.mlearning import create_regression_model
    from gemseo.mlearning import get_regression_models

    if algorithm not in get_regression_models():
        msg = f"GEMSEO has no regression model named {algorithm}."
        raise SurrogateError(msg)
    try:
        return create_regression_model(
            algorithm, dataset, transformer=TRANSFORMER, **settings
        )
    except (TypeError, ValueError) as error:
        msg = f"The settings of {algorithm} are not valid: {error}"
        raise SurrogateError(msg) from None


def _folds(n_samples: int, n_folds: int, seed: int) -> list[np.ndarray]:
    """The samples of each fold, shuffled."""
    order = np.random.default_rng(seed).permutation(n_samples)
    return [fold for fold in np.array_split(order, n_folds) if len(fold)]


def r2_scores(observed: np.ndarray, predicted: np.ndarray) -> list[float]:
    """The coefficient of determination of each component."""
    residual = ((observed - predicted) ** 2).sum(axis=0)
    total = ((observed - observed.mean(axis=0)) ** 2).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r2 = np.where(total > 0, 1 - residual / total, np.nan)
    return [float(value) for value in r2]


def _rmse(observed: np.ndarray, predicted: np.ndarray) -> list[float]:
    """The root mean square error of each component."""
    return [
        float(value) for value in np.sqrt(((observed - predicted) ** 2).mean(axis=0))
    ]


def _json_floats(values: np.ndarray) -> list[Any]:
    return [None if not np.isfinite(value) else float(value) for value in values]


def train(
    folder: str,
    inputs: list[str],
    outputs: list[str],
    algorithm: str,
    settings: dict[str, Any],
    n_folds: int,
    model_file: str,
    seed: int = 1,
) -> dict[str, Any]:
    """Train a surrogate, measure its quality and pickle it.

    Args:
        folder: The run folder.
        inputs: The input variables.
        outputs: The output variables.
        algorithm: The name of a GEMSEO regression model.
        settings: Its settings.
        n_folds: The number of folds of the cross-validation (2 at least).
        model_file: Where to pickle the trained model.
        seed: The seed shuffling the samples between the folds.

    Returns:
        The quality (``r2`` and ``rmse`` on the training data, ``r2_cv`` and
        ``rmse_cv`` by cross-validation, one value per component of each output),
        the points of the charts, and the variables with their bounds.
    """
    require_gemseo()
    from gemseo import to_pickle

    dataset, input_values, output_values = training_data(folder, inputs, outputs)
    n_samples = len(next(iter(input_values.values())))
    n_folds = max(2, min(n_folds, n_samples))
    model = regression_model(dataset, algorithm, settings)
    model.learn()
    learned = model.predict(input_values)

    cross_validated = {
        name: np.zeros_like(values) for name, values in output_values.items()
    }
    for fold in _folds(n_samples, n_folds, seed):
        training = np.setdiff1d(np.arange(n_samples), fold)
        fold_model = regression_model(dataset, algorithm, settings)
        fold_model.learn(samples=training.tolist())
        predicted = fold_model.predict(
            {name: values[fold] for name, values in input_values.items()}
        )
        for name in outputs:
            cross_validated[name][fold] = predicted[name]

    quality = {}
    points = {}
    shown = np.linspace(0, n_samples - 1, min(n_samples, MAX_POINTS)).astype(int)
    for name, observed in output_values.items():
        quality[name] = {
            "r2": r2_scores(observed, learned[name]),
            "rmse": _rmse(observed, learned[name]),
            "r2_cv": r2_scores(observed, cross_validated[name]),
            "rmse_cv": _rmse(observed, cross_validated[name]),
        }
        points[name] = [
            {
                "observed": _json_floats(observed[shown, component]),
                "learned": _json_floats(learned[name][shown, component]),
                "cross_validated": _json_floats(
                    cross_validated[name][shown, component]
                ),
            }
            for component in range(observed.shape[1])
        ]
    path = Path(model_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    to_pickle(model, path)
    return {
        "n_samples": n_samples,
        "n_folds": n_folds,
        "quality": quality,
        "points": points,
        "inputs": [
            {
                "name": name,
                "size": values.shape[1],
                "lower": values.min(axis=0).tolist(),
                "upper": values.max(axis=0).tolist(),
                "default": values.mean(axis=0).tolist(),
            }
            for name, values in input_values.items()
        ],
        "outputs": [
            {"name": name, "size": values.shape[1]}
            for name, values in output_values.items()
        ],
    }


def _variables(params: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    return variables(str(params.get("folder")))


def _train(params: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    return train(
        str(params.get("folder")),
        list(params.get("inputs") or []),
        list(params.get("outputs") or []),
        str(params.get("algorithm")),
        dict(params.get("settings") or {}),
        int(params.get("n_folds") or 5),
        str(params.get("model_file")),
    )


def register(server: Any) -> None:
    """Add the surrogate methods to the worker."""
    server.add("surrogate.variables", _variables)
    server.add("surrogate.train", _train)
