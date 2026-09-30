"""A model and its surrogate: the normal model, and a fast copy of it.

The surrogate is a regression model trained on samples of the normal model.
The optimization loops on the surrogates; its result is validated on the
normal models, and the surrogates learn more samples around it when they were
not accurate enough there (see validation.py).

The samples are saved in HDF5 files, and the surrogates are trained on them
each time they are created, in a fraction of a second: nothing is pickled, and
reading the samples runs no code.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import h5py
from gemseo import compute_doe, create_design_space, create_surrogate
from gemseo.core.discipline import Discipline
from gemseo.datasets.io_dataset import IODataset
from gemseo.disciplines.surrogate import SurrogateDiscipline
from numpy import clip, float64, vstack
from numpy.typing import NDArray

MODELS = Path(__file__).parent / "models"
"""The samples the surrogates are trained on."""

Physics = Callable[..., dict[str, NDArray[float64]]]


@dataclass(frozen=True)
class ModelDuo:
    """A normal model and its surrogate, trained on samples of it."""

    name: str
    model: type[Discipline]
    physics: Physics
    bounds: dict[str, tuple[float, float]]
    outputs: tuple[str, ...]
    n_samples: int = 200

    @property
    def samples_file(self) -> Path:
        """The file of the samples the surrogate is trained on."""
        return MODELS / f"{self.name.lower()}.h5"

    def normal(self) -> Discipline:
        """Create the normal model."""
        return self.model()

    def surrogate(self) -> SurrogateDiscipline:
        """Create the surrogate, trained on the samples (drawn the first time)."""
        if not self.samples_file.is_file():
            self.sample(self.initial_samples())
        return create_surrogate(
            "RBFRegressor", read_training_data(self.samples_file), disc_name=self.name
        )

    def initial_samples(self) -> NDArray[float64]:
        """Draw samples filling the ranges of the inputs (Latin hypercube).

        The ranges are widened a little, so that their bounds are inside the
        domain the surrogate learnt.
        """
        design_space = create_design_space()
        for name, (lower, upper) in self.bounds.items():
            margin = 0.02 * (upper - lower)
            design_space.add_variable(
                name, lower_bound=lower - margin, upper_bound=upper + margin
            )
        samples: NDArray[float64] = compute_doe(
            design_space, algo_name="LHS", n_samples=self.n_samples, seed=1
        )
        return samples

    def sample(self, inputs: NDArray[float64]) -> None:
        """Evaluate the normal model at the inputs and save the samples.

        The physics of the model is called directly, not the discipline.
        """
        columns = {name: inputs[:, i : i + 1] for i, name in enumerate(self.bounds)}
        outputs = self.physics(**columns)
        MODELS.mkdir(exist_ok=True)
        with h5py.File(self.samples_file, "w", track_order=True) as file:
            group = file.create_group("inputs", track_order=True)
            for name, values in columns.items():
                group.create_dataset(name, data=values)
            group = file.create_group("outputs", track_order=True)
            for name in self.outputs:
                group.create_dataset(name, data=outputs[name])

    def enrich(self, point: dict[str, float], n_samples: int = 20) -> None:
        """Learn more samples of the normal model around a point.

        Args:
            point: The values of the inputs to learn better around (and others).
            n_samples: The number of samples added.

        """
        around = self.initial_samples()[:n_samples]
        for i, (name, (lower, upper)) in enumerate(self.bounds.items()):
            # Within 5 % of the range around the point.
            unit = (around[:, i] - lower) / (upper - lower) - 0.5
            around[:, i] = clip(
                point[name] + 0.1 * unit * (upper - lower), lower, upper
            )
        learnt = read_training_data(self.samples_file).input_dataset.to_numpy()
        self.sample(vstack([learnt, around]))


def read_training_data(file_path: Path) -> IODataset:
    """Read the samples a surrogate is trained on: its inputs and outputs."""
    dataset = IODataset()
    with h5py.File(file_path, "r") as file:
        for name, values in file["inputs"].items():
            dataset.add_input_variable(name, values[()])
        for name, values in file["outputs"].items():
            dataset.add_output_variable(name, values[()])
    return dataset
