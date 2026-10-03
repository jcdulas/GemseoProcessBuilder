"""Exploring other zones of the design space, in other processes (spec § 4.11).

When Claude has a reading of the design space, it may ask for one to four
*explorations*: runs of the problem from other starting designs, each in a
process of its own, that Claude does not guide. Each applies the user's
algorithm and settings for a few outer iterations (10 by default) and stops on a
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

import json
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
from pathlib import Path
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

INTERRUPT_GRACE = 600.0
"""Seconds an exploration asked to stop has to do so, before it is ended: it stops
at the end of its current outer iteration, which takes about a minute."""

TREND_WINDOW = 10
"""The last outer iterations the progress of an exploration is measured over."""

EXIT_ITERATIONS = 10
"""The outer iterations an exploration may spend outside the feasible domain (the
optimizer's ``outside``: most of the constraints violated), on top of its own."""

EXIT_SECONDS = 900.0
"""The seconds an exploration may spend outside the feasible domain."""


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

    progress_path: str = ""
    """Where the process tells how far it is, after each outer iteration."""

    stop_path: str = ""
    """A file whose existence asks the process to stop: it ends at the end of its
    current outer iteration, on a feasible point, and answers as usual."""

    exit_iterations: int = EXIT_ITERATIONS
    """The outer iterations the exploration may spend outside the feasible
    domain, which do not count among its ``iterations``."""

    exit_seconds: float = EXIT_SECONDS
    """The seconds it may spend there."""


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

    saturation: float | None = None
    """The share of the inequality constraints at their limit or violated at the
    starting design."""

    exit_iterations: int = 0
    """The outer iterations spent outside the feasible domain (``iterations``
    counts the others)."""

    unfinished: str = ""
    """Why the exploration was ended before it left the feasible domain's
    outside (its iterations or seconds there were spent); empty otherwise."""


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
        outcome.saturation = _saturation(
            problem, float(settings.get("ineq_tolerance", 1e-5))
        )
        settings["log_problem"] = False
        notes: dict[str, str] = {}
        if job.algo_name in LSO_ALGORITHMS:
            _follow_outer_iterations(problem, job, reports, started, notes)
            settings["save_state"] = job.state_path
            settings["max_iter"] = (
                job.iterations + job.exit_iterations
            ) * EVALUATIONS_PER_ITERATION
        else:
            settings["max_iter"] = job.iterations
        scenario.execute(algo_name=job.algo_name, **settings)
        _read_outcome(outcome, problem, job, settings, reports)
        outcome.unfinished = notes.get("unfinished", "")
    except Exception as error:  # A failed exploration says so, it breaks nothing.
        outcome.error = f"{type(error).__name__}: {error}"
    outcome.seconds = round(time.perf_counter() - started, 1)
    return outcome


def _saturation(problem: Any, tolerance: float) -> float | None:
    """The share of the inequality constraints saturated at the current design.

    Their components at their limit (within ``tolerance``) or violated; ``None``
    when the problem has no inequality constraint. It costs one evaluation of the
    constraints, which the optimizer then finds in the database.
    """
    constraints = [
        function for function in problem.constraints if function.f_type == "ineq"
    ]
    if not constraints:
        return None
    values, _ = problem.evaluate_functions(
        problem.design_space.get_current_value(),
        False,
        output_functions=constraints,
    )
    flat = np.concatenate(
        [np.atleast_1d(np.asarray(values[function.name])) for function in constraints]
    )
    return float(np.mean(flat >= -tolerance))


def _follow_outer_iterations(
    problem: Any,
    job: Job,
    reports: list[dict[str, Any]],
    started: float,
    notes: dict[str, str],
) -> None:
    """Tell how far the optimizer is, and stop it, on a feasible point, in time.

    The iterations outside the feasible domain (most of the constraints
    violated) have a budget of their own, in iterations and in seconds: a start
    far from it may need them to get anywhere, but not forever.
    """
    from gemseo_lso.gemseo.live import forget
    from gemseo_lso.gemseo.live import on_open

    def follow(run: Any) -> None:
        def count(report: Any) -> None:
            reports.append(asdict(report))
            _write_progress(job, reports, started)
            outside = sum(1 for item in reports if item.get("outside"))
            inside = len(reports) - outside
            spent = time.perf_counter() - started
            if inside >= job.iterations:
                run.stop("exploration over", when_feasible=True)
            elif job.stop_path and Path(job.stop_path).exists():
                run.stop("exploration interrupted", when_feasible=True)
            elif report.outside and (
                outside >= job.exit_iterations or spent >= job.exit_seconds
            ):
                notes["unfinished"] = (
                    f"still outside the feasible domain after {outside} "
                    f"iterations and {spent:.0f} s: ended"
                )
                run.stop("exploration ended outside the domain")

        run.watch(count)

    forget(problem)
    on_open(problem, follow)


def _write_progress(job: Job, reports: list[dict[str, Any]], started: float) -> None:
    """Tell how far an exploration is, for whoever follows it (a small file)."""
    if not job.progress_path:
        return
    last = reports[-1]
    measured = progress(reports[-TREND_WINDOW:])
    data = {
        "iteration": int(last["iteration"]),
        "of": job.iterations,
        "outside": bool(last.get("outside")),
        "objective": float(last["objective"]),
        "max_constraint": float(last["max_constraint"]),
        "kkt_residual": float(last["kkt_residual"]),
        "gain_per_iteration": None if measured is None else measured.gain,
        "seconds": round(time.perf_counter() - started, 1),
    }
    path = Path(job.progress_path)
    try:  # Written whole, then renamed: a reader never sees half of it.
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data), "utf-8")
        os.replace(temporary, path)
    except OSError:  # A look at it at that moment: the next one will do.
        pass


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
    outcome.exit_iterations = sum(1 for item in reports if item.get("outside"))
    outcome.iterations = len(reports) - outcome.exit_iterations
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


def available_memory_gb() -> float | None:
    """The memory the machine can still give, in GB; ``None`` if it cannot be read."""
    try:
        if os.name == "nt":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("load", ctypes.c_ulong),
                    ("total", ctypes.c_ulonglong),
                    ("available", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("available_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended", ctypes.c_ulonglong),
                ]

            status = Status()
            status.length = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return float(status.available) / 2**30
        with open("/proc/meminfo", encoding="utf-8") as file:
            for line in file:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 2**20
    except (OSError, ValueError, AttributeError):
        return None
    return None


class Handle:
    """A running exploration: asks whether it has ended, and ends it."""

    def poll(self) -> Outcome | None:
        """The outcome once it has ended, else ``None``."""
        raise NotImplementedError

    def stop(self) -> None:
        """End it now."""
        raise NotImplementedError

    def progress(self) -> dict[str, Any] | None:
        """How far it is, as of its last outer iteration; ``None`` if unknown."""
        return None

    def interrupt(self) -> None:
        """Ask it to end at the end of its current outer iteration."""


class _Process(Handle):
    """An exploration in a process of its own."""

    def __init__(self, job: Job, threads: int, timeout: float) -> None:
        context = multiprocessing.get_context("spawn")
        self._queue: Any = context.Queue()
        self._job = job
        self._timeout = timeout
        self._started = time.monotonic()
        self._interrupted: float | None = None
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
            if (
                self._interrupted is not None
                and time.monotonic() - self._interrupted > INTERRUPT_GRACE
            ):
                self.stop()
                return Outcome(self._job.label, error="it did not stop when asked")
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

    def interrupt(self) -> None:
        if self._interrupted is None and self._job.stop_path:
            Path(self._job.stop_path).write_text("stop", "utf-8")
            self._interrupted = time.monotonic()

    def progress(self) -> dict[str, Any] | None:
        try:
            data: dict[str, Any] = json.loads(
                Path(self._job.progress_path).read_text("utf-8")
            )
        except (OSError, ValueError):
            return None
        return data


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

    max_processes: int = 3
    """Explorations run at the same time, at most."""

    min_processes: int = 2
    """Explorations run at the same time, at least, whatever the memory."""

    memory_per_process_gb: float = 5.0
    """The memory an exploration takes: 4 to 5 GB measured on the bracket of 10⁴
    elements, a copy of the model and of its vectors in each process."""

    memory_reserve_gb: float = 4.0
    """The memory kept free for the main run and the rest of the machine."""

    threads: int | None = None
    """The threads of the numerical libraries of each process; by default twice
    what the cores shared with the main run would give (``cores // 5``): 4 on 12
    cores."""

    max_iterations: int = 10
    """Outer iterations of an exploration."""

    max_explorations: int = 2
    """Times Claude may explore in a run."""

    exit_iterations: int = EXIT_ITERATIONS
    """The outer iterations an exploration may spend outside the feasible domain
    (most of the constraints violated), on top of its own ``max_iterations``."""

    exit_seconds: float = EXIT_SECONDS
    """The seconds it may spend there."""

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
        self.threads = settings.threads or max(1, 2 * ((os.cpu_count() or 2) // 5))
        """The threads of each process."""

    @property
    def active(self) -> bool:
        """Whether an exploration is running."""
        return bool(self.running)

    def max_starts(self) -> int:
        """The explorations that can start now: 2 or 3, by the memory available.

        Each takes ``memory_per_process_gb``, and ``memory_reserve_gb`` stays free;
        never fewer than ``min_processes`` nor more than ``max_processes``. Without
        a way to read the memory, the most.
        """
        settings = self.settings
        free = available_memory_gb()
        if free is None:
            return settings.max_processes
        fit = int((free - settings.memory_reserve_gb) // settings.memory_per_process_gb)
        return max(settings.min_processes, min(settings.max_processes, fit))

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

    def interrupt(self, labels: list[str] | None = None) -> list[str]:
        """Ask explorations to end at the end of their current outer iteration.

        Args:
            labels: Those to stop; all the running ones by default.

        Returns:
            The labels asked to stop. They answer as usual, shorter, on a feasible
            point and with their state saved: they can still be adopted.
        """
        asked = [
            label for label in (labels or list(self.running)) if label in self.running
        ]
        for label in asked:
            self.running[label].interrupt()
        return asked

    def progress(self) -> dict[str, dict[str, Any]]:
        """How far each running exploration is."""
        found = {label: handle.progress() for label, handle in self.running.items()}
        return {label: data for label, data in found.items() if data is not None}

    def seconds(self, label: str) -> float:
        """How long an exploration has run."""
        return time.monotonic() - self.started.get(label, time.monotonic())

    def stop(self) -> None:
        """End the explorations still running."""
        for handle in self.running.values():
            handle.stop()
        self.running.clear()
