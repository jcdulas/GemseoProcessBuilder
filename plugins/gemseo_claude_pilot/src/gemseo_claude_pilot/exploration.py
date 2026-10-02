"""Exploring other zones of the design space, in other processes (spec § 4.11).

When Claude has a reading of the design space, it may ask for one to four
*explorations*: runs of the problem from other starting designs, each in a
process of its own, that Claude does not guide. Each applies the user's
algorithm and settings for a few outer iterations (50 at most) and stops on a
feasible point; the pilot gives Claude what each reached and how it was still
progressing, and Claude decides whether to move its main run onto one of them
(``adopt``), the optimizer resuming the state the exploration saved.

The processes are started with the ``spawn`` method: a process shares nothing
with the one that runs the main optimization (the problem, its database and
its disciplines keep a state). They build their own scenario with the
``factory`` the user gives (a function that creates a new scenario of the
problem, picklable: a function of a module or a ``functools.partial``) and
each uses a share of the cores, so that the main run is not starved.
"""

import multiprocessing
import os
import queue
import time
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Any

import numpy as np

from gemseo_claude_pilot.progress import progress
from gemseo_claude_pilot.snapshots import database_entries
from gemseo_claude_pilot.snapshots import history_from_entries
from gemseo_claude_pilot.snapshots import snapshot_problem

LSO_ALGORITHMS = ("LSO_MMA", "LSO_GCMMA")

EVALUATIONS_PER_ITERATION = 8
"""The evaluations an exploration may spend per outer iteration it is allowed:
a safety cap, GCMMA makes about three."""

THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMBA_NUM_THREADS",
)
"""What bounds the threads of the numerical libraries of a process."""

TREND_WINDOW = 10
"""The last outer iterations the progress of an exploration is measured over."""


@dataclass(frozen=True)
class Job:
    """One exploration: a process, a starting design, a number of iterations."""

    label: str
    factory: Callable[[], Any]
    algo_name: str
    settings: dict[str, Any]
    x0: list[float]
    """The starting design, in the units of GEMSEO."""

    iterations: int
    state_path: str
    """Where the optimizer saves its state at the end, to be resumed if adopted."""


@dataclass
class Outcome:
    """What an exploration reached."""

    label: str
    iterations: int = 0
    evaluations: int = 0
    seconds: float = 0.0
    start_objective: float | None = None
    start_violation: float | None = None
    best_objective: float | None = None
    """The best feasible objective met (in the minimized form of the history)."""

    best_x: list[float] | None = None
    final_objective: float | None = None
    final_violation: float | None = None
    """The maximum constraint at the last iterate."""

    gain_per_iteration: float | None = None
    """The relative gain of the objective per iteration over its last iterations."""

    state_path: str = ""
    error: str = ""
    why: str = ""
    """What Claude explained about this start, kept for the report."""


def run_exploration(job: Job) -> Outcome:
    """Run an exploration to its end, in this process (the work of a worker).

    The user's algorithm from the starting design, no Claude: for the large-scale
    optimizer it stops after ``iterations`` outer iterations, on a feasible
    point; for another algorithm after as many evaluations.
    """
    started = time.perf_counter()
    outcome = Outcome(job.label, state_path=job.state_path)
    try:
        scenario = job.factory()
        problem = scenario.formulation.optimization_problem
        space = problem.design_space
        space.set_current_value(
            np.clip(
                np.asarray(job.x0, dtype=float),
                space.get_lower_bounds(),
                space.get_upper_bounds(),
            )
        )
        reports: list[dict[str, Any]] = []
        settings = {
            key: value
            for key, value in job.settings.items()
            if key not in ("resume_from", "save_state")
        }
        settings["log_problem"] = False
        if job.algo_name in LSO_ALGORITHMS:
            _follow_outer_iterations(problem, job.iterations, reports)
            settings["save_state"] = job.state_path
            settings["max_iter"] = job.iterations * EVALUATIONS_PER_ITERATION
        else:
            settings["max_iter"] = job.iterations
        scenario.execute(algo_name=job.algo_name, **settings)
        _read_outcome(outcome, problem, job, settings, reports)
    except Exception as error:  # A failed exploration says so, it breaks nothing.
        outcome.error = f"{type(error).__name__}: {error}"
    outcome.seconds = round(time.perf_counter() - started, 1)
    return outcome


def _follow_outer_iterations(
    problem: Any, iterations: int, reports: list[dict[str, Any]]
) -> None:
    """Stop the optimizer, on a feasible point, after some outer iterations."""
    from gemseo_lso.gemseo.live import forget
    from gemseo_lso.gemseo.live import on_open

    def follow(run: Any) -> None:
        def count(report: Any) -> None:
            reports.append(asdict(report))
            if len(reports) >= iterations:
                run.stop("exploration over", when_feasible=True)

        run.watch(count)

    forget(problem)
    on_open(problem, follow)


def _read_outcome(
    outcome: Outcome,
    problem: Any,
    job: Job,
    settings: dict[str, Any],
    reports: list[dict[str, Any]],
) -> None:
    """What a finished exploration reached, from its database and its reports."""
    snapshot = snapshot_problem(
        problem, job.algo_name, int(settings["max_iter"]), settings
    )
    history = history_from_entries(database_entries(problem), snapshot)
    outcome.evaluations = history.n_evaluations
    outcome.iterations = len(reports)
    outcome.start_objective = float(history.objective[0])
    outcome.start_violation = float(history.violation[0])
    if history.best_index >= 0:
        outcome.best_objective = float(history.objective[history.best_index])
        outcome.best_x = [float(value) for value in history.best_x]
    if reports:
        outcome.final_objective = float(reports[-1]["objective"])
        outcome.final_violation = float(reports[-1]["max_constraint"])
        measured = progress(reports[-TREND_WINDOW:])
        if measured is not None:
            outcome.gain_per_iteration = measured.gain


class Handle:
    """A running exploration: asks whether it has ended, and ends it."""

    def poll(self) -> Outcome | None:
        """The outcome once it has ended, else ``None``."""
        raise NotImplementedError

    def stop(self) -> None:
        """End it now."""
        raise NotImplementedError


class _Process(Handle):
    """An exploration in a process of its own."""

    def __init__(self, job: Job, threads: int, timeout: float) -> None:
        context = multiprocessing.get_context("spawn")
        self._queue: Any = context.Queue()
        self._job = job
        self._timeout = timeout
        self._started = time.monotonic()
        self._process = context.Process(
            target=_child, args=(job, self._queue), daemon=True
        )
        with _threads(threads):
            self._process.start()

    def poll(self) -> Outcome | None:
        try:
            outcome: Outcome = self._queue.get_nowait()
        except queue.Empty:
            if time.monotonic() - self._started > self._timeout:
                self.stop()
                return Outcome(self._job.label, error="it exceeded its time limit")
            if not self._process.is_alive():
                try:  # It may have answered just before ending.
                    return self._queue.get(timeout=0.5)  # type: ignore[no-any-return]
                except queue.Empty:
                    return Outcome(self._job.label, error="its process ended")
            return None
        return outcome

    def stop(self) -> None:
        if self._process.is_alive():
            self._process.terminate()


def _child(job: Job, results: Any) -> None:
    """The entry point of an exploration process."""
    results.put(run_exploration(job))


@contextmanager
def _threads(count: int) -> Iterator[None]:
    """Processes started inside get this many threads for their numerical libraries."""
    saved = {name: os.environ.get(name) for name in THREAD_VARIABLES}
    os.environ.update({name: str(count) for name in THREAD_VARIABLES})
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


Launcher = Callable[[Job, int, float], Handle]
"""Starts a job with a number of threads and a time limit; a test gives its own."""


@dataclass(frozen=True)
class ExplorationSettings:
    """What the user allows the pilot to explore with."""

    factory: Callable[[], Any]
    """Creates a new scenario of the problem, with its algorithm's disciplines:
    a function of a module, or a ``functools.partial`` of one (picklable)."""

    max_processes: int = 4
    """Explorations run at the same time."""

    max_iterations: int = 50
    """Outer iterations of an exploration."""

    max_explorations: int = 2
    """Times Claude may explore in a run."""

    timeout: float = 3600.0
    """Seconds after which an exploration is ended."""

    launch: Launcher | None = field(default=None, compare=False)
    """How to start a job; a process by default."""


class Explorer:
    """Starts the explorations of a run, follows them and ends them.

    Args:
        settings: What the user allows.
    """

    def __init__(self, settings: ExplorationSettings) -> None:
        self.settings = settings
        self.running: dict[str, Handle] = {}
        self.started: dict[str, float] = {}
        self.threads = max(1, (os.cpu_count() or 2) // (settings.max_processes + 1))
        """The threads of each process: the cores shared with the main run."""

    @property
    def active(self) -> bool:
        """Whether an exploration is running."""
        return bool(self.running)

    def start(self, jobs: list[Job]) -> None:
        """Start the explorations of a decision, one process each."""
        launch = self.settings.launch or _Process
        for job in jobs:
            self.running[job.label] = launch(job, self.threads, self.settings.timeout)
            self.started[job.label] = time.monotonic()

    def poll(self) -> list[Outcome]:
        """The explorations that have ended since the last look."""
        ended = []
        for label, handle in list(self.running.items()):
            outcome = handle.poll()
            if outcome is not None:
                del self.running[label]
                ended.append(outcome)
        return ended

    def seconds(self, label: str) -> float:
        """How long an exploration has run."""
        return time.monotonic() - self.started.get(label, time.monotonic())

    def stop(self) -> None:
        """End the explorations still running."""
        for handle in self.running.values():
            handle.stop()
        self.running.clear()
