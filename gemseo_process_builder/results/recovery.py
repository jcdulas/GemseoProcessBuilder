"""The results of a run killed after saving its history at each evaluation.

A run killed saves nothing at its end (SPEC § 11.4): no ``dataset.csv``, no
variables in its ``run.json``. When its driver saved the history after each
evaluation (SPEC § 6.4), ``history.h5`` holds the problem and its database:
the results are written from it the first time they are read (in the worker:
GEMSEO reads the file).
"""

import json
from pathlib import Path
from typing import Any

from gemseo_process_builder.results.models import VariableInfo
from gemseo_process_builder.results.models import read_info
from gemseo_process_builder.results.models import write_info

HISTORY = "history.h5"


def recoverable(folder: Path) -> bool:
    """Whether a run has a history but no dataset."""
    return (folder / HISTORY).is_file() and not (folder / "dataset.csv").is_file()


def recover(folder: Path) -> bool:
    """Write the dataset and the variables of a run from its history.

    Returns:
        Whether the history held evaluations.
    """
    import numpy as np
    from gemseo.algos.optimization_problem import OptimizationProblem

    problem = OptimizationProblem.from_hdf(folder / HISTORY)
    if not len(problem.database):
        return False
    dataset = problem.database.to_dataset()
    dataset.to_csv(folder / "dataset.csv")
    values = dataset.to_numpy(dtype=float, na_value=np.nan)
    np.save(folder / "dataset.npy", np.asfortranarray(values))
    info = read_info(folder)
    if info is not None and not info.variables:
        info.variables = [
            VariableInfo.model_validate(item)
            for item in _variables(problem, _is_doe(folder))
        ]
        info.summary.n_evaluations = len(problem.database)
        info.summary.objective = problem.objective.name
        write_info(folder, info)
    return True


def _is_doe(folder: Path) -> bool:
    """Whether the run evaluated samples (its mapping counts them)."""
    try:
        mapping = json.loads((folder / "script.gpb-map.json").read_text("utf-8"))
    except (OSError, ValueError):
        return False
    return bool(mapping.get("progress", {}).get("unit") == "sample")


def _variables(problem: Any, is_doe: bool) -> list[dict[str, Any]]:
    """The variables of the results, with their roles (as the runner gives them)."""
    space = problem.design_space
    variables: list[dict[str, Any]] = [
        {
            "name": name,
            "size": int(space.variable_sizes[name]),
            "role": "design variable",
            "lower": _finite(space.get_lower_bound(name)),
            "upper": _finite(space.get_upper_bound(name)),
        }
        for name in space.variable_names
    ]
    variables.append(
        {"name": problem.objective.name, "role": "output" if is_doe else "objective"}
    )
    variables += [
        {"name": c.name, "role": "constraint", "constraint_type": c.f_type}
        for c in problem.constraints
    ]
    role = "output" if is_doe else "observable"
    variables += [{"name": o.name, "role": role} for o in problem.observables]
    return variables


def _finite(values: Any) -> list[float | None]:
    import math

    return [None if math.isinf(value) else float(value) for value in values]
