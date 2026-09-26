"""The maintenance cost: a surrogate model, trained once and saved.

The maintenance cost comes from a costly fleet study; a regression model
(radial basis functions) replaces it, trained on samples of it the first time
the study runs, then saved next to this file and loaded from it.
"""

from pathlib import Path

from gemseo import from_pickle, to_pickle
from gemseo.datasets.io_dataset import IODataset
from gemseo.disciplines.surrogate import SurrogateDiscipline
from gemseo.mlearning.regression.algos.rbf import RBFRegressor
from numpy import float64
from numpy.random import default_rng
from numpy.typing import NDArray

MODEL = Path(__file__).parent / "models" / "maintenance.pkl"
"""The trained model."""

N_SAMPLES = 40


def fleet_study(
    flight_range: NDArray[float64], weight_ratio: NDArray[float64]
) -> NDArray[float64]:
    """Compute the maintenance cost per flight (the costly study, a formula here)."""
    return 150.0 + 0.05 * flight_range + 400.0 * weight_ratio**2


def train_model(path: Path) -> None:
    """Sample the fleet study, train the regression model and save it."""
    samples = default_rng(seed=1).random((N_SAMPLES, 2))
    flight_range = 300.0 + 3700.0 * samples[:, :1]
    weight_ratio = samples[:, 1:]
    dataset = IODataset()
    dataset.add_variable("y_4", flight_range, group_name=IODataset.INPUT_GROUP)
    dataset.add_variable("y_11", weight_ratio, group_name=IODataset.INPUT_GROUP)
    dataset.add_variable(
        "maintenance",
        fleet_study(flight_range, weight_ratio),
        group_name=IODataset.OUTPUT_GROUP,
    )
    model = RBFRegressor(dataset)
    model.learn()
    path.parent.mkdir(exist_ok=True)
    to_pickle(model, path)


def maintenance_surrogate() -> SurrogateDiscipline:
    """Create the maintenance cost from the range and the weight ratio."""
    if not MODEL.is_file():
        train_model(MODEL)
    surrogate = SurrogateDiscipline(from_pickle(MODEL))
    surrogate.name = "Maintenance"
    return surrogate
