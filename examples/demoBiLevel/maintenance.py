"""The maintenance cost: a surrogate model, trained on samples saved once.

The maintenance cost comes from a costly fleet study; a regression model
(radial basis functions) replaces it. The fleet study is sampled the first time
the study runs, and the samples are saved next to this file (HDF5); the model
is trained on them each time, in a fraction of a second. Nothing is pickled:
reading the samples runs no code.
"""

from pathlib import Path

import h5py
from gemseo import create_surrogate
from gemseo.datasets.io_dataset import IODataset
from gemseo.disciplines.surrogate import SurrogateDiscipline
from numpy import float64
from numpy.random import default_rng
from numpy.typing import NDArray

SAMPLES = Path(__file__).parent / "models" / "maintenance.h5"
"""The samples of the fleet study."""

N_SAMPLES = 40


def fleet_study(
    flight_range: NDArray[float64], weight_ratio: NDArray[float64]
) -> NDArray[float64]:
    """Compute the maintenance cost per flight (the costly study, a formula here)."""
    return 150.0 + 0.05 * flight_range + 400.0 * weight_ratio**2


def sample_fleet_study(path: Path) -> None:
    """Sample the fleet study and save the samples: inputs, then outputs."""
    samples = default_rng(seed=1).random((N_SAMPLES, 2))
    flight_range = 300.0 + 3700.0 * samples[:, :1]
    weight_ratio = samples[:, 1:]
    path.parent.mkdir(exist_ok=True)
    with h5py.File(path, "w", track_order=True) as file:
        inputs = file.create_group("inputs", track_order=True)
        inputs.create_dataset("y_4", data=flight_range)
        inputs.create_dataset("y_11", data=weight_ratio)
        outputs = file.create_group("outputs", track_order=True)
        outputs.create_dataset(
            "maintenance", data=fleet_study(flight_range, weight_ratio)
        )


def read_training_data(file_path: Path) -> IODataset:
    """Read the samples a surrogate is trained on: its inputs and outputs."""
    dataset = IODataset()
    with h5py.File(file_path, "r") as file:
        for name, values in file["inputs"].items():
            dataset.add_input_variable(name, values[()])
        for name, values in file["outputs"].items():
            dataset.add_output_variable(name, values[()])
    return dataset


def maintenance_surrogate() -> SurrogateDiscipline:
    """Create the maintenance cost from the range and the weight ratio."""
    if not SAMPLES.is_file():
        sample_fleet_study(SAMPLES)
    return create_surrogate(
        "RBFRegressor", read_training_data(SAMPLES), disc_name="Maintenance"
    )
