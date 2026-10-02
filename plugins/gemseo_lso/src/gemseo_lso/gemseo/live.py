"""What a running LSO algorithm shares with a pilot (spec § 8).

GEMSEO runs an algorithm in one call: nothing can reach it between two of its
iterations. ``LSO_MMA`` and ``LSO_GCMMA`` open a ``LiveRun`` on their problem
for the time of the run; a pilot (the Claude copilot) finds it with
``live_run(problem)`` and

- reads the report of each outer iteration (``reports``, or a listener);
- changes settings, applied at the next outer iteration without a restart:
  nothing of the state is lost (``change``);
- switches MMA and GCMMA (``switch``);
- moves the design, the optimizer going on from there with its state
  (``move``): a pilot steering the run toward where it heads;
- brings the iterate back within the constraints now, without waiting for the
  end of the budget (``restore_feasibility``);
- stops the run, or asks for its state to be saved (``stop``, ``save``);
- reads the multipliers of each constraint and the stationarity of each design
  variable at the last iteration (``multipliers``, ``stationarity``): how much
  of the objective each constraint costs, where the KKT residual comes from.

The settings GEMSEO owns (``max_iter``, ``ftol_rel``…, the tolerances it checks
the result with) and those needing the model (``jacobian_mode``,
``sparsity_pattern``) cannot change live: a pilot starts a new segment for them.

Example:
    >>> run = live_run(scenario.formulation.optimization_problem)
    >>> if run is not None:
    ...     run.change({"screening_margin": 0.4})
"""

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from dataclasses import fields
from dataclasses import replace
from pathlib import Path
from typing import Any
from typing import Literal

import numpy as np

from gemseo_lso.core.arrays import Array
from gemseo_lso.core.optimizer import Optimizer
from gemseo_lso.core.report import Report
from gemseo_lso.core.settings import Settings

NOT_LIVE = frozenset(
    {
        "method",
        "max_iter",
        "max_evaluations",
        "ftol_rel",
        "xtol_rel",
        "stall_iterations",
        "ineq_tolerance",
        "eq_tolerance",
        "jacobian_mode",
    }
)
"""Settings of the core that do not change during a run: owned by GEMSEO, or
needing the model."""

LIVE_SETTINGS = frozenset(item.name for item in fields(Settings)) - NOT_LIVE
"""The settings a pilot may change between two outer iterations."""

Listener = Callable[[Report], None]


@dataclass
class LiveRun:
    """The live side of a running LSO algorithm, between two outer iterations."""

    algorithm: str
    """``LSO_MMA`` or ``LSO_GCMMA``, as started."""

    settings: dict[str, Any]
    """The settings of the core now, live changes included."""

    reports: list[Report] = field(default_factory=list)
    listeners: list[Listener] = field(default_factory=list)
    constraints: dict[str, slice] = field(default_factory=dict)
    """Where each inequality constraint (GEMSEO's name) is among all of them."""

    variables: dict[str, slice] = field(default_factory=dict)
    """Where each design variable is in the design vector."""

    optimizer: Optimizer | None = None
    """The optimizer, once the run has started."""

    to_optimizer: Callable[[Array], Array] | None = None
    """A design vector of GEMSEO in the space of the optimizer."""

    _move: Array | None = None
    _changes: dict[str, Any] = field(default_factory=dict)
    _method: Literal["mma", "gcmma"] | None = None
    _stop: str = ""
    _stop_when_feasible: bool = False
    _save: list[Path] = field(default_factory=list)
    _restore: bool = False

    def watch(self, listener: Listener) -> None:
        """Call ``listener`` with the report of each outer iteration."""
        self.listeners.append(listener)

    def change(self, settings: Mapping[str, Any]) -> None:
        """Change settings at the next outer iteration.

        Raises:
            ValueError: When a setting cannot change live, or a value is out of
                its range (the whole change is refused).
        """
        fixed = sorted(set(settings) - LIVE_SETTINGS)
        if fixed:
            msg = f"These settings cannot change during a run: {', '.join(fixed)}."
            raise ValueError(msg)
        merged = {**self.settings, **self._changes, **settings}
        Settings(**merged)  # Raises SettingsError, a ValueError, when invalid.
        self._changes.update(settings)

    def switch(self, method: Literal["mma", "gcmma"]) -> None:
        """Run MMA or GCMMA from the next outer iteration, from the same state."""
        if method not in ("mma", "gcmma"):
            msg = f"The method is mma or gcmma, not {method}."
            raise ValueError(msg)
        self._method = method

    def move(self, x: Array) -> None:
        """Go on from this design vector (GEMSEO's units) at the next outer iteration.

        The optimizer keeps its asymptotes, multipliers and working set; the
        point is clipped into the bounds and evaluated once.
        """
        self._move = np.array(x, dtype=float)

    def restore_feasibility(self) -> None:
        """Bring the iterate back within the constraints from the next outer iteration.

        Smaller moves and a larger cost of the violation, until the point is
        feasible or ``restoration_iterations`` iterations have passed; nothing
        when it is feasible already.
        """
        self._restore = True

    def stop(
        self, reason: str = "stopped on request", when_feasible: bool = False
    ) -> None:
        """End the run after the current outer iteration.

        With ``when_feasible``, an iterate outside the constraints is first
        brought back within them (at most ``restoration_iterations`` more
        iterations), and the run ends there.
        """
        self._stop = reason
        self._stop_when_feasible = when_feasible

    def save(self, path: Path | str) -> None:
        """Save the state after the current outer iteration (HDF5)."""
        self._save.append(Path(path))

    def multipliers(self) -> dict[str, Array]:
        """The multipliers of each inequality constraint at the last iteration.

        In the units of the objective per unit of the constraint: how much the
        objective would gain if the constraint were relaxed by one unit; zero
        out of the working set.
        """
        optimizer = self.optimizer
        if optimizer is None:
            return {}
        state = optimizer.state
        values = (state.objective_scale or 1.0) * state.multipliers
        return {name: values[part].copy() for name, part in self.constraints.items()}

    def stationarity(self) -> dict[str, Array]:
        """The projected gradient of the Lagrangian per design variable.

        In the space the optimizer works in (normalized when the design space
        is); empty before the first iteration.
        """
        optimizer = self.optimizer
        if optimizer is None or not optimizer.stationarity.size:
            return {}
        values = optimizer.stationarity
        return {name: np.array(values[part]) for name, part in self.variables.items()}

    def apply(self, optimizer: Optimizer) -> None:
        """Apply what was asked for since the last outer iteration (the library)."""
        self.optimizer = optimizer
        settings = optimizer.settings
        if self._changes:
            settings = replace(settings, **self._changes)
            self._changes = {}
        if self._method is not None:
            settings = replace(settings, method=self._method)
            if self._method == "mma":
                optimizer.state.gcmma_since = -1  # MMA again, as asked.
            self._method = None
        optimizer.settings = settings
        self.settings = _values(settings)
        if self._move is not None:
            x = self._move
            self._move = None
            optimizer.move(self.to_optimizer(x) if self.to_optimizer else x)
        if self._restore:
            self._restore = False
            optimizer.restore_feasibility()
        for path in self._save:
            optimizer.state.save(path)
        self._save = []
        if self._stop:
            optimizer.stop(self._stop, self._stop_when_feasible)
            self._stop = ""

    def publish(self, report: Report) -> None:
        """Give the report of an outer iteration to the listeners (the library)."""
        self.reports.append(report)
        for listener in list(self.listeners):
            listener(report)


_RUNS: dict[int, LiveRun] = {}
"""The live runs, by problem."""

_WATCHERS: dict[int, list[Callable[[LiveRun], None]]] = {}
"""What to call with the live run of a problem when it opens, by problem."""


def live_run(problem: object) -> LiveRun | None:
    """The live run of an LSO algorithm on a problem, while it runs."""
    return _RUNS.get(id(problem))


def on_open(problem: object, callback: Callable[[LiveRun], None]) -> None:
    """Call ``callback`` with the live run each time one opens on a problem.

    A pilot learns of a run before its first iteration, whatever the points it
    evaluates: points already in the database do not announce themselves.
    """
    _WATCHERS.setdefault(id(problem), []).append(callback)


def forget(problem: object) -> None:
    """Forget the callbacks of ``on_open`` for a problem."""
    _WATCHERS.pop(id(problem), None)


def open_run(
    problem: object,
    algorithm: str,
    settings: Settings,
    constraints: Mapping[str, slice] | None = None,
    variables: Mapping[str, slice] | None = None,
    to_optimizer: Callable[[Array], Array] | None = None,
) -> LiveRun:
    """Open the live run of a problem (the library, at the start of a run).

    Args:
        problem: The GEMSEO problem.
        algorithm: The name of the algorithm.
        settings: The settings of the core.
        constraints: Where each inequality constraint is among all of them.
        variables: Where each design variable is in the design vector.
        to_optimizer: A design vector of GEMSEO in the space of the optimizer.
    """
    run = LiveRun(
        algorithm,
        _values(settings),
        constraints=dict(constraints or {}),
        variables=dict(variables or {}),
        to_optimizer=to_optimizer,
    )
    _RUNS[id(problem)] = run
    for callback in list(_WATCHERS.get(id(problem), [])):
        callback(run)
    return run


def close_run(problem: object) -> None:
    """Close the live run of a problem (the library, at the end of a run)."""
    _RUNS.pop(id(problem), None)


def _values(settings: Settings) -> dict[str, Any]:
    return {item.name: getattr(settings, item.name) for item in fields(Settings)}
