"""Events describing a run as it goes (SPEC § 11.3).

- Iterations and samples come from a listener on the ``Database`` of the
  optimization problem. GEMSEO calls it when a new point starts, before all
  its outputs are known, so each point is reported when the next one starts
  (and the last one at the end).
- Discipline states come from GEMSEO 6's execution status observers
  (``configure(enable_discipline_status=True)``); no wrapper is needed.
- Nested scenarios (SPEC § 6.3) report their own iterations as
  ``inner_progress`` events, a secondary indicator next to the progress of the
  run.
- When the samples of a DOE run in several processes, the disciplines execute
  in the child processes: only the progress is reported then.

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
    """Every discipline, including those inside chains, MDAs and nested scenarios.

    Chains, MDAs and the scenarios given to a BiLevel formulation list their
    disciplines in ``disciplines``; a scenario adapter holds its ``scenario``.
    """
    for discipline in disciplines:
        yield discipline
        yield from walk(getattr(discipline, "disciplines", ()))
        scenario = getattr(discipline, "scenario", None)
        if scenario is not None:
            yield from walk(scenario.disciplines)


def top_disciplines(scenario: Any) -> list[Any]:
    """The disciplines of a scenario, with the adapters BiLevel creates."""
    adapters = getattr(scenario.formulation, "scenario_adapters", [])
    return [*scenario.disciplines, *adapters]


class _Shared:
    """An observer that GEMSEO may copy along with what it observes.

    BiLevel keeps a copy of the database of each sub-scenario after each run
    (``keep_opt_history``): the copies report to the same run, and the event
    channel (holding locks) cannot be copied anyway.
    """

    def __deepcopy__(self, memo: dict[int, Any]) -> "_Shared":
        return self


class StatusObserver(_Shared):
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


class InnerProgressListener(_Shared):
    """Report the iterations of a nested scenario, run many times by its parent."""

    def __init__(
        self, node_id: str, scenario: Any, limiter: RateLimiter, stop: StopFlag
    ) -> None:
        self.node_id = node_id
        self.name = scenario.name
        self.database = scenario.formulation.optimization_problem.database
        self.limiter = limiter
        self.stop = stop
        self.database.add_new_iter_listener(self.new_point)

    def new_point(self, x: Any) -> None:
        """Called by GEMSEO when a new point of the nested scenario starts."""
        # The database only holds the current run of the nested scenario.
        self.limiter.emit(
            "inner_progress",
            {"node_id": self.node_id, "name": self.name, "current": len(self.database)},
            key=f"inner:{self.node_id}",
        )
        self.stop.check()


def observe_nested_scenarios(
    disciplines: Any, mapping: dict[str, Any], limiter: RateLimiter, stop: StopFlag
) -> list[str]:
    """Follow the iterations of the nested scenarios; return their node ids."""
    node_of = {name: node_id for node_id, name in mapping.get("scenarios", {}).items()}
    observed = []
    for item in walk(disciplines):
        scenario = getattr(item, "scenario", item)
        node_id = node_of.get(getattr(scenario, "name", None))
        if node_id and node_id not in observed and hasattr(scenario, "formulation"):
            InnerProgressListener(node_id, scenario, limiter, stop)
            observed.append(node_id)
    return observed


class ProblemListener(_Shared):
    """Report the iterations (or samples) of a scenario's optimization problem."""

    def __init__(
        self,
        problem: Any,
        limiter: RateLimiter,
        stop: StopFlag,
        unit: str,
        total: int | None,
        processes: int = 1,
    ) -> None:
        self.problem = problem
        self.database = problem.database
        self.limiter = limiter
        self.stop = stop
        self.unit = unit
        self.total = total
        self.processes = processes
        """The processes evaluating the samples; beyond one, no discipline states."""

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
        progress = {"current": self.index, "total": self.total, "unit": self.unit}
        if self.processes > 1:
            progress["processes"] = self.processes
        self.limiter.emit("progress", progress, key="progress")

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
