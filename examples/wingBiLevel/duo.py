"""A model and its surrogate: the normal model, and a fast copy of it.

The surrogate is a regression model trained on samples of the normal model.
The optimization loops on the surrogates; its result is validated on the
normal models, and the surrogates learn more samples around it when they were
not accurate enough there (see validation.py).
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gemseo import compute_doe, create_design_space, from_pickle, to_pickle
from gemseo.core.discipline import Discipline
from gemseo.datasets.io_dataset import IODataset
from gemseo.disciplines.surrogate import SurrogateDiscipline
from gemseo.mlearning.regression.algos.rbf import RBFRegressor
from numpy import clip, float64, load, save, vstack
from numpy.typing import NDArray

MODELS = Path(__file__).parent / "models"
"""The trained surrogates and their samples."""

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
    def model_file(self) -> Path:
        """The file of the trained surrogate."""
        return MODELS / f"{self.name.lower()}.pkl"

    @property
    def samples_file(self) -> Path:
        """The file of the inputs the surrogate was trained on."""
        return MODELS / f"{self.name.lower()}_samples.npy"

    def normal(self) -> Discipline:
        """Create the normal model."""
        return self.model()

    def surrogate(self) -> SurrogateDiscipline:
        """Create the surrogate, trained the first time."""
        if not self.model_file.is_file():
            self.train(self.initial_samples())
        surrogate = SurrogateDiscipline(from_pickle(self.model_file))
        surrogate.name = self.name
        return surrogate

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

    def train(self, inputs: NDArray[float64]) -> None:
        """Evaluate the normal model at the inputs and train the surrogate on it.

        The physics of the model is called directly, not the discipline.
        """
        columns = {name: inputs[:, i : i + 1] for i, name in enumerate(self.bounds)}
        outputs = self.physics(**columns)
        dataset = IODataset()
        for name, values in columns.items():
            dataset.add_variable(name, values, group_name=IODataset.INPUT_GROUP)
        for name in self.outputs:
            dataset.add_variable(name, outputs[name], group_name=IODataset.OUTPUT_GROUP)
        model = RBFRegressor(
            dataset,
            transformer={
                IODataset.INPUT_GROUP: "MinMaxScaler",
                IODataset.OUTPUT_GROUP: "MinMaxScaler",
            },
        )
        model.learn()
        MODELS.mkdir(exist_ok=True)
        to_pickle(model, self.model_file)
        save(self.samples_file, inputs)

    def enrich(self, point: dict[str, float], n_samples: int = 20) -> None:
        """Learn more samples of the normal model around a point, and train again.

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
        self.train(vstack([load(self.samples_file), around]))
