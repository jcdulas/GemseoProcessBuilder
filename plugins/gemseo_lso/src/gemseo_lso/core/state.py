"""The state of the optimizer, saved and restored exactly (spec § 5).

Everything the next iteration depends on is here, except the row cache (it
may hold gigabytes) and the colored Jacobian (computed again at the first
iteration after a restart: exactly the same with ``jacobian_refresh`` 1, not
after Schubert updates): restoring a saved state continues the run as if it had
never stopped when the rows are computed at every iteration (``row_refresh``
``always``); with ``near_active``, the rows of the first iteration after the
restart are computed again. States are saved in HDF5, never pickled.
"""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import fields
from pathlib import Path
from typing import BinaryIO
from typing import Literal

import numpy as np

from gemseo_lso.core.arrays import Array
from gemseo_lso.core.arrays import Indices

Status = Literal[
    "running",
    "converged",
    "stalled",
    "max_iter",
    "ftol",
    "xtol",
    "stopped",
    "max_rows",
]

STATE_VERSION = 7

_ARRAYS = (
    "x",
    "constraints",
    "multipliers",
    "equalities",
    "equality_multipliers",
    "constraints_previous",
    "working_set",
    "constraint_scales",
    "x_previous",
    "x_before",
    "lower_asymptote",
    "upper_asymptote",
    "best_x",
)


_LISTS = ("history", "kkt_history", "step_history")


@dataclass
class State:
    """Where the optimizer is."""

    x: Array
    """The iterate."""

    objective: float
    """``f(x)``."""

    constraints: Array
    """``g(x)``, all of them."""

    multipliers: Array
    """The multipliers of the last subproblem, one per constraint (zero out of
    its working set)."""

    equalities: Array = field(default_factory=lambda: np.zeros(0))
    """``h(x)``, all of them."""

    equality_multipliers: Array = field(default_factory=lambda: np.zeros(0))
    """The multipliers of the pairs ``h - ε <= 0``, then ``-h - ε <= 0``."""

    equality_band: float = 1.0
    """The current ``ε`` of the pairs ``±h - ε <= 0``."""

    constraints_previous: Array | None = None
    """``g`` at the previous iterate: the screening margin follows its change."""

    working_set: Indices | None = None
    """The constraints of the last subproblem."""

    constraint_scales: Array | None = None
    """The largest change of each constraint when one variable crosses its
    range, from its last row; 0 while none was computed. The screening divides
    the constraints by it."""

    x_previous: Array | None = None
    x_before: Array | None = None
    lower_asymptote: Array | None = None
    upper_asymptote: Array | None = None
    iteration: int = 0
    evaluations: int = 1
    """The evaluations of the values (the starting point is one)."""

    row_evaluations: int = 0
    """The constraint gradients asked for."""

    directional_derivatives: int = 0
    """``hybrid``: the directional derivatives asked for."""

    objective_stall: int = 0
    """Consecutive iterations where the objective hardly changed."""

    x_stall: int = 0
    """Consecutive iterations where the point hardly moved."""

    status: Status = "running"
    message: str = ""
    history: list[float] = field(default_factory=list)
    """The objective at each iterate."""

    kkt_history: list[float] = field(default_factory=list)
    """The KKT residual at each iterate."""

    step_history: list[float] = field(default_factory=list)
    """The largest move of a variable at each step, relative to its range."""

    gcmma_since: int = -1
    """The iteration MMA switched to GCMMA at, having cycled (-1: it did not)."""

    restoration: int = 0
    """The iterations spent restoring feasibility so far (0: not restoring)."""

    descent: int = 0
    """The iterations spent in the descent through the constraints so far; -1
    once it has ended (``descent_iterations``)."""

    best_x: Array | None = None
    """The best feasible point met, if any."""

    best_objective: float = float("inf")
    best_max_constraint: float = float("nan")
    best_iteration: int = -1

    objective_scale: float = 0.0
    """The largest change of the objective when one variable crosses its
    range, at the start: the subproblem divides the objective by it, so that
    its multipliers and its tolerances do not depend on the units."""

    gradient_scale: float = 0.0
    """The largest component of the gradient of the objective at the start: the
    KKT residual is never measured against less than a thousandth of it."""

    def save(self, path: Path | str | BinaryIO) -> None:
        """Write the state to an HDF5 file, or to a binary file object."""
        import h5py

        with h5py.File(path, "w") as file:
            file.attrs["version"] = STATE_VERSION
            for item in fields(self):
                value = getattr(self, item.name)
                if item.name in _ARRAYS:
                    if value is not None:
                        file.create_dataset(item.name, data=value)
                elif item.name in _LISTS:
                    file.create_dataset(item.name, data=np.asarray(value, dtype=float))
                else:
                    file.attrs[item.name] = value

    @classmethod
    def load(cls, path: Path | str | BinaryIO) -> "State":
        """Read a state written by ``save``."""
        import h5py

        with h5py.File(path, "r") as file:
            version = int(file.attrs["version"])
            if version != STATE_VERSION:
                msg = f"{path} holds a state of version {version}, not {STATE_VERSION}."
                raise ValueError(msg)
            values: dict[str, object] = {}
            for item in fields(cls):
                if item.name in _ARRAYS:
                    values[item.name] = (
                        np.array(file[item.name][()]) if item.name in file else None
                    )
                elif item.name in _LISTS:
                    values[item.name] = [float(v) for v in file[item.name][()]]
                else:
                    raw = file.attrs[item.name]
                    values[item.name] = raw.item() if hasattr(raw, "item") else raw
        values["objective"] = float(values["objective"])  # type: ignore[arg-type]
        return cls(**values)  # type: ignore[arg-type]
