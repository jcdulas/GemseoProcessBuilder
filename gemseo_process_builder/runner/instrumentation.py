"""Events describing a run as it goes (SPEC § 11.3).

- Iterations and samples come from a listener on the ``Database`` of the
  optimization problem. GEMSEO calls it when a new point starts, before all
  its outputs are known, so each point is reported when the next one starts
  (and the last one at the end).
- Discipline states come from GEMSEO 6's execution status observers
  (``configure(enable_discipline_status=True)``); no wrapper is needed.

The instrumented objects are duck-typed: this module does not import GEMSEO,
so that the runner protocol can be tested without it.
"""

import logging
from collections.abc import Iterator
from typing import Any

from gemseo_process_builder.runner.rate_limiter import RateLimiter
from gemseo_process_builder.runner.stop import StopFlag

STATES = {
    "RUNNING": "running",
    "LINEARIZING": "running",
    "DONE": "done",
    "FAILED": "failed",
}


def plain(value: Any) -> Any:
    """A JSON-friendly value: arrays become lists, 1-element lists numbers."""
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, list) and len(value) == 1:
        return value[0]
    return value


def walk(disciplines: Any) -> Iterator[Any]:
    """Every discipline, including those inside chains and MDAs."""
    for discipline in disciplines:
        yield discipline
        yield from walk(getattr(discipline, "disciplines", ()))


class StatusObserver:
    """Report the state of one discipline (a GEMSEO execution status observer)."""

    def __init__(self, node_id: str, limiter: RateLimiter, stop: StopFlag) -> None:
        self.node_id = node_id
        self.limiter = limiter
        self.stop = stop

    def update_status(self, execution_status: Any) -> None:
        """Called by GEMSEO when the status changes."""
        state = STATES.get(str(execution_status.value), "running")
        self.limiter.emit(
            "status", {"node_id": self.node_id, "state": state}, key=self.node_id
        )
        if state == "running":
            self.stop.check()


def observe_disciplines(
    disciplines: Any, mapping: dict[str, Any], limiter: RateLimiter, stop: StopFlag
) -> list[str]:
    """Attach status observers; return the ids of the observed nodes."""
    node_of = {
        name: node_id for node_id, name in mapping.get("disciplines", {}).items()
    }
    observed = []
    for discipline in walk(disciplines):
        node_id = node_of.get(getattr(discipline, "name", None))
        status = getattr(discipline, "execution_status", None)
        if node_id and status is not None and node_id not in observed:
            status.add_observer(StatusObserver(node_id, limiter, stop))
            observed.append(node_id)
    for node_id in observed:
        limiter.emit("status", {"node_id": node_id, "state": "pending"}, key=node_id)
    return observed


class ProblemListener:
    """Report the iterations (or samples) of a scenario's optimization problem."""

    def __init__(
        self,
        problem: Any,
        limiter: RateLimiter,
        stop: StopFlag,
        unit: str,
        total: int | None,
    ) -> None:
        self.problem = problem
        self.database = problem.database
        self.limiter = limiter
        self.stop = stop
        self.unit = unit
        self.total = total
        self.index = 0
        self._pending: Any = None
        self.database.add_new_iter_listener(self.new_point)

    def new_point(self, x: Any) -> None:
        """Called by GEMSEO when a new point starts: report the previous one."""
        self.report_pending()
        self._pending = x
        self.stop.check()

    def report_pending(self) -> None:
        """Report the point waiting for its outputs, if any."""
        if self._pending is None:
            return
        x, self._pending = self._pending, None
        self.index += 1
        values = self._values(x)
        if self.unit == "sample":
            self.limiter.emit(
                "sample",
                {"index": self.index, "inputs": self._inputs(x), "outputs": values},
            )
        else:
            self.limiter.emit("iteration", self._iteration(x, values))
        self.limiter.emit(
            "progress",
            {"current": self.index, "total": self.total, "unit": self.unit},
            key="progress",
        )

    def _inputs(self, x: Any) -> dict[str, Any]:
        converted = self.problem.design_space.convert_array_to_dict(x)
        return {name: plain(value) for name, value in converted.items()}

    def _values(self, x: Any) -> dict[str, Any]:
        names = [self.problem.objective.name]
        names += [function.name for function in self.problem.constraints]
        names += [function.name for function in self.problem.observables]
        return {
            name: plain(self.database.get_function_value(name, x)) for name in names
        }

    def _iteration(self, x: Any, values: dict[str, Any]) -> dict[str, Any]:
        constraints = {c.name: c.f_type for c in self.problem.constraints}
        inequalities = {
            n: values[n] for n, kind in constraints.items() if kind == "ineq"
        }
        equalities = {n: values[n] for n, kind in constraints.items() if kind == "eq"}
        objective = self.problem.objective.name
        return {
            "index": self.index,
            "x": self._inputs(x),
            "f": {objective: values[objective]},
            "g": inequalities,
            "h": equalities,
            "observables": {o.name: values[o.name] for o in self.problem.observables},
            "feasible": _feasible(inequalities, equalities),
        }


INEQUALITY_TOLERANCE = 1e-4
EQUALITY_TOLERANCE = 1e-2
"""GEMSEO's default tolerances on the constraints."""


def _elements(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _feasible(inequalities: dict[str, Any], equalities: dict[str, Any]) -> bool | None:
    """Whether the constraints hold; ``None`` while a value is unknown."""
    values = list(inequalities.values()) + list(equalities.values())
    if any(value is None for value in values):
        return None
    inequalities_hold = all(
        element <= INEQUALITY_TOLERANCE
        for value in inequalities.values()
        for element in _elements(value)
    )
    equalities_hold = all(
        abs(element) <= EQUALITY_TOLERANCE
        for value in equalities.values()
        for element in _elements(value)
    )
    return inequalities_hold and equalities_hold


class LogForwarder(logging.Handler):
    """Send the log records of the run as ``log`` events."""

    def __init__(self, limiter: RateLimiter) -> None:
        super().__init__(logging.INFO)
        self.limiter = limiter

    def emit(self, record: logging.LogRecord) -> None:
        """Forward one record."""
        try:
            message = record.getMessage()
        except Exception:  # A broken log call must not stop the run.
            message = str(record.msg)
        self.limiter.emit(
            "log",
            {
                "level": record.levelname,
                "logger": record.name,
                "message": message,
                "time": record.created,
            },
        )
