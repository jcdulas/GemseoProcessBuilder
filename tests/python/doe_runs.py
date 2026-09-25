"""Tiny DOE run folders for the surrogate tests."""

from pathlib import Path

import numpy as np

from gemseo_process_builder.results.models import RunInfo
from gemseo_process_builder.results.models import VariableInfo
from gemseo_process_builder.results.models import write_info


def rosenbrock(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return (1 - x) ** 2 + 100 * (y - x**2) ** 2


def rosenbrock_run(folder: Path, n_samples: int = 30, failed: int = 0) -> Path:
    """A DOE run of the Rosenbrock function over [-2, 2]², as the runner writes it.

    Args:
        folder: Where to create the run folder.
        n_samples: The number of evaluations.
        failed: How many of them failed (NaN outputs).
    """
    run = folder / "r-doe"
    run.mkdir(parents=True)
    samples = np.random.default_rng(3).uniform(-2.0, 2.0, (n_samples, 2))
    values = rosenbrock(samples[:, 0], samples[:, 1])
    values[:failed] = np.nan
    lines = [
        "GROUP,inputs,inputs,outputs",
        "VARIABLE,x,y,f",
        "COMPONENT,0,0,0",
        *(
            f"{index},{x},{y},{'' if np.isnan(f) else f}"
            for index, (x, y, f) in enumerate(zip(*samples.T, values, strict=True))
        ),
    ]
    (run / "dataset.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_info(
        run,
        RunInfo(
            id="r-doe",
            driver="n-study",
            driver_name="Study",
            status="completed",
            created="2026-09-25T10:00:00",
            variables=[
                VariableInfo(name="x", role="design variable", lower=[-2], upper=[2]),
                VariableInfo(name="y", role="design variable", lower=[-2], upper=[2]),
                VariableInfo(name="f", role="observable"),
            ],
        ),
    )
    return run


def points_of(run: Path) -> list[tuple[float, float]]:
    """The (x, y) samples of a run made by ``rosenbrock_run``."""
    lines = (run / "dataset.csv").read_text(encoding="utf-8").splitlines()[3:]
    return [(float(line.split(",")[1]), float(line.split(",")[2])) for line in lines]
