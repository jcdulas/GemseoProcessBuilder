"""Rows chained through the displacements: products against the full Jacobian (plan 76).

Run it with:
    python plugins/gemseo_lso/benchmarks/run_split_topology.py [rows|iterations|...]

The steps are ``rows``, ``iterations``, ``agreement``, ``optimum`` and
``acceptance``; without an argument, all of them in turn. The
stress-constrained L-bracket of ``run_topology.py`` is split into two
disciplines: the displacements (the intermediate) and the stresses (rows). The
rows of the stresses are chained through the displacements:

- **products**: by their vector-Jacobian products, one adjoint solve per row on
  the factorization of the point (``AdjointDisplacementsDiscipline``);
- **full**: by their Jacobian, formed by GEMSEO, one solve per element, dense
  (``DisplacementsDiscipline``).

``rows`` measures what an iteration costs the model on each path, through the
adapter of ``LSO_MMA`` and ``LSO_GCMMA`` (``GemseoProblem``): the evaluation of a
point, then the rows of 1,000 constraints (the working set of an iteration, the
most loaded elements), in a process of its own per run (its memory is its own),
the fastest of three runs per size (the machine is shared); it fits
``t = a N^b`` on each path. The optimizer's own work is the same on both paths:
it receives the same rows. The full Jacobian of 10⁵ elements (2·10⁵ degrees of
freedom × 10⁵ elements: 169 GB) is out of reach: its time and memory at 10⁵ are
extrapolated from its ladder, with one-sided 95 % prediction bounds.

``iterations`` runs two outer iterations of ``LSO_MMA`` at 10⁴ elements on each
path, from the same start: the time and memory of the second. ``agreement``
compares the rows of both paths at the iterates of a run. ``optimum`` runs both
paths to the end on a small bracket, and the path of the products again with
its rows perturbed by 10⁻¹² of their values: how far round-off alone moves the
optimum of this problem. ``acceptance`` judges "the same optimum" from the
results of ``agreement`` and ``optimum`` as the owner accepted it (2026-10-23):
the rows equal to 1e-12 at the iterates, both optima feasible and their
objectives within 0.5 % (``gemseo_lso.benchmarks.topology.split.acceptance``).

Every run lasts under a minute. The results are written to
``benchmarks/results/split_topology.json``.
"""

import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import psutil

RESULTS = Path(__file__).parent / "results"
OUTPUT = RESULTS / "split_topology.json"

ROWS = 1000
"""The rows asked for at a point: a working set."""

REPEATS = 3
"""Runs per size of the ladders: the fastest is kept."""

PRODUCT_SIZES = (125, 177, 250, 400)
"""Elements across: 10⁴, 2·10⁴, 4·10⁴ and 10⁵ elements."""

FULL_SIZES = (35, 50, 71, 100, 125)
"""Elements across: 800 to 10⁴ elements (the dense Jacobian of 10⁴: 1.6 GB)."""

TARGET = 102_400
"""The elements of the bracket of 400 across."""

COMPARED = 125
"""Elements across of the iterations compared: 10⁴ elements."""

SMALL = 35
"""Elements across of the runs to the end: 784 elements."""

SETTINGS: dict[str, Any] = {
    "move_limit": 0.2,
    "row_batch_size": ROWS,
    "max_working_set": ROWS,
    "max_iter": 10_000,
}
"""``run_topology.py``'s MMA, at most 1,000 rows in the working set; the run is
stopped after two outer iterations."""


class Sampler:
    """The largest resident memory of the process while it runs, sampled."""

    def __init__(self, period: float = 0.005) -> None:
        self.process = psutil.Process()
        self.period = period
        self.peak = 0
        self._running = True
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def _sample(self) -> None:
        while self._running:
            self.peak = max(self.peak, self.process.memory_info().rss)
            time.sleep(self.period)

    def reset(self) -> int:
        """Start a new peak from now; the resident memory now."""
        now = int(self.process.memory_info().rss)
        self.peak = now
        return now

    def stop(self) -> None:
        """Stop sampling."""
        self._running = False
        self._thread.join()


def scenario(size: int, path: str) -> tuple[Any, Any, Any]:
    """The scenario of the split bracket; the topology problem, the displacements."""
    from gemseo import create_design_space
    from gemseo import create_scenario

    from gemseo_lso.benchmarks.topology.cases import l_bracket
    from gemseo_lso.benchmarks.topology.split import split_disciplines

    logging.getLogger("gemseo").setLevel(logging.WARNING)
    logging.getLogger("gemseo_lso").setLevel(logging.WARNING)
    problem = l_bracket(size)
    displacements, stresses, volume = split_disciplines(problem, path != "full")
    space = create_design_space()
    space.add_variable(
        "x", size=problem.elements, lower_bound=0.0, upper_bound=1.0, value=1.0
    )
    study = create_scenario(
        [volume, displacements, stresses],
        "volume",
        space,
        formulation_name="DisciplinaryOpt",
    )
    study.add_constraint("stress", "ineq")
    return study, problem, displacements


def adapter(size: int, path: str) -> tuple[Any, Any, Any]:
    """The adapter of the optimizer, the topology problem, the displacements."""
    from gemseo_lso.gemseo.adapter import GemseoProblem
    from gemseo_lso.gemseo.settings import LSO_MMA_Settings

    study, problem, displacements = scenario(size, path)
    optimization = study.formulation.optimization_problem
    optimization.preprocess_functions()
    return GemseoProblem(optimization, LSO_MMA_Settings()), problem, displacements


def design(problem: Any) -> np.ndarray:
    """A point between full and void: smooth, the same at every size."""
    x, y = problem.centers.T / problem.mask.shape[1]
    return 0.55 + 0.4 * np.cos(3 * np.pi * x) * np.cos(2 * np.pi * y)


def rows_run(path: str, size: int) -> dict[str, Any]:
    """The evaluation of a point and the rows of 1,000 constraints, measured."""
    adapted, problem, displacements = adapter(size, path)
    sampler = Sampler()
    x = design(problem)
    start = sampler.reset()
    begin = time.perf_counter()
    _, constraints, _ = adapted.values(x)
    evaluated = time.perf_counter()
    rows = np.sort(np.argsort(constraints)[-ROWS:])
    adapted.constraint_rows(x, rows)
    end = time.perf_counter()
    sampler.stop()
    return {
        "path": path,
        "across": size,
        "elements": problem.elements,
        "degrees_of_freedom": int(problem.free.size),
        "rows": ROWS,
        "evaluation_seconds": evaluated - begin,
        "rows_seconds": end - evaluated,
        "seconds_per_iteration": end - begin,
        "extra_memory_gb_per_iteration": (sampler.peak - start) / 1e9,
        "displacements_jacobians": displacements.jacobians,
        "adjoint_rows": displacements.product_rows,
        "dense_jacobian_gb": problem.free.size * problem.elements * 8 / 1e9,
    }


def iterations_run(path: str, size: int) -> dict[str, Any]:
    """Two outer iterations of ``LSO_MMA``: the second one measured."""
    from gemseo_lso.gemseo.live import on_open

    study, problem, displacements = scenario(size, path)
    sampler = Sampler()
    marks: list[dict[str, Any]] = []

    def watch(live: Any) -> None:
        def listener(report: Any) -> None:
            marks.append(
                {
                    "time": time.perf_counter(),
                    "peak": sampler.peak,
                    "rows": report.rows_computed,
                    "volume": report.objective,
                }
            )
            marks[-1]["start"] = sampler.reset()
            if len(marks) == 2:
                live.stop("measured")

        live.watch(listener)

    on_open(study.formulation.optimization_problem, watch)
    study.execute(algo_name="LSO_MMA", **SETTINGS)
    sampler.stop()
    first, second = marks
    return {
        "path": path,
        "elements": problem.elements,
        "seconds_per_iteration": second["time"] - first["time"],
        "extra_memory_gb_per_iteration": (second["peak"] - first["start"]) / 1e9,
        "rows_per_iteration": second["rows"],
        "displacements_jacobians": displacements.jacobians,
        "adjoint_rows": displacements.product_rows,
        "volume": [first["volume"], second["volume"]],
    }


def optimum_run(path: str, size: int) -> dict[str, Any]:
    """``LSO_MMA`` to the end; ``perturbed``: the products, rows perturbed."""
    from gemseo_lso.gemseo.sources import Chaining

    if path == "perturbed":
        original = Chaining.rows
        noise = np.random.default_rng(0)

        def perturbed(self: Any, *args: Any, **kwargs: Any) -> list[Any]:
            blocks = original(self, *args, **kwargs)
            return [
                block * (1 + 1e-12 * noise.standard_normal(block.shape))
                for block in blocks
            ]

        Chaining.rows = perturbed  # type: ignore[method-assign]
    study, problem, displacements = scenario(size, path)
    start = time.perf_counter()
    study.execute(algo_name="LSO_MMA", move_limit=0.2, max_iter=300, ftol_rel=1e-4)
    result = study.optimization_result
    np.save(RESULTS / f"split_optimum_{path}.npy", result.x_opt)
    return {
        "path": path,
        "elements": problem.elements,
        "volume": float(result.f_opt),
        "feasible": bool(result.is_feasible),
        "seconds": time.perf_counter() - start,
        "evaluations": len(study.formulation.optimization_problem.database),
        "displacements_jacobians": displacements.jacobians,
    }


def in_process(*arguments: str) -> dict[str, Any]:
    """One run in a process of its own: its memory is its own."""
    command = [sys.executable, __file__, "one", *arguments]
    start = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr)
    entry: dict[str, Any] = json.loads(completed.stdout.strip().splitlines()[-1])
    entry["run_seconds"] = time.perf_counter() - start
    print(f"{arguments}: {json.dumps(entry)}", flush=True)
    return entry


def fit(sizes: list[float], values: list[float], target: float) -> dict[str, Any]:
    """``value = a N^b`` in log-log: R², and the value at ``target`` with its bounds.

    The bounds are the one-sided 95 % prediction bounds of the log-log line.
    """
    from scipy import stats

    x, y = np.log(sizes), np.log(values)
    line = stats.linregress(x, y)
    residuals = y - (line.intercept + line.slope * x)
    count = len(x)
    spread = np.sqrt(np.sum(residuals**2) / (count - 2))
    leverage = (
        1 + 1 / count + (np.log(target) - x.mean()) ** 2 / np.sum((x - x.mean()) ** 2)
    )
    margin = stats.t.ppf(0.95, count - 2) * spread * np.sqrt(leverage)
    center = line.intercept + line.slope * np.log(target)
    return {
        "exponent": float(line.slope),
        "r2": float(line.rvalue**2),
        "at_target": float(np.exp(center)),
        "lower_95": float(np.exp(center - margin)),
        "upper_95": float(np.exp(center + margin)),
    }


def save(key: str, value: Any) -> None:
    """Record a result in the results file."""
    RESULTS.mkdir(exist_ok=True)
    results = json.loads(OUTPUT.read_text("utf-8")) if OUTPUT.is_file() else {}
    results[key] = value
    OUTPUT.write_text(json.dumps(results, indent=2), "utf-8")


def fastest(path: str, size: int) -> dict[str, Any]:
    """The fastest of ``REPEATS`` runs, with the times of all."""
    runs = [in_process("rows", path, str(size)) for _ in range(REPEATS)]
    best = min(runs, key=lambda entry: entry["seconds_per_iteration"])
    best["all_seconds"] = [entry["seconds_per_iteration"] for entry in runs]
    return best


def rows_ladder() -> None:
    """Both paths at their sizes, and the fits of their costs."""
    runs = [fastest("full", size) for size in FULL_SIZES]
    runs += [fastest("products", size) for size in PRODUCT_SIZES]
    fits = {}
    for path in ("full", "products"):
        mine = [entry for entry in runs if entry["path"] == path]
        sizes = [entry["elements"] for entry in mine]
        fits[path] = {
            key: fit(sizes, [max(entry[key], 1e-4) for entry in mine], TARGET)
            for key in (
                "seconds_per_iteration",
                "rows_seconds",
                "extra_memory_gb_per_iteration",
            )
        }
    save("rows", {"runs": runs, "fits": fits})
    print(json.dumps(fits, indent=2))


def iterations() -> None:
    """Two iterations of each path at 10⁴ elements."""
    runs = {
        path: in_process("iterations", path, str(COMPARED))
        for path in ("products", "full")
    }
    save("iterations", runs)


def agreement(size: int = 50, points: int = 6) -> None:
    """The rows of both paths at the iterates of a run of the products."""
    study, _, _ = scenario(size, "products")
    study.execute(algo_name="LSO_MMA", move_limit=0.2, max_iter=60)
    database = study.formulation.optimization_problem.database
    iterates = [
        np.asarray(database.get_x_vect(index))
        for index in np.linspace(1, len(database), points).astype(int)
    ]
    products, _, _ = adapter(size, "products")
    full, _, _ = adapter(size, "full")
    differences = []
    for x in iterates:
        _, constraints, _ = products.values(x)
        full.values(x)
        rows = np.sort(np.argsort(constraints)[-200:])
        given = np.asarray(products.constraint_rows(x, rows))
        expected = np.asarray(full.constraint_rows(x, rows))
        scale = np.linalg.norm(expected, axis=1)
        differences.append(
            float((np.linalg.norm(given - expected, axis=1) / scale).max())
        )
    entry = {
        "elements": int(iterates[0].size),
        "iterates": len(iterates),
        "rows_per_iterate": 200,
        "max_relative_row_difference": differences,
    }
    save("agreement", entry)
    print(json.dumps(entry), flush=True)


def optimum() -> None:
    """Both paths to the end, and the products with perturbed rows."""
    runs = {
        path: in_process("optimum", path, str(SMALL))
        for path in ("products", "full", "perturbed")
    }
    designs = {path: np.load(RESULTS / f"split_optimum_{path}.npy") for path in runs}
    entry = {
        "runs": runs,
        "max_design_difference": {
            "products_full": float(np.abs(designs["products"] - designs["full"]).max()),
            "products_perturbed": float(
                np.abs(designs["products"] - designs["perturbed"]).max()
            ),
        },
    }
    save("optimum", entry)
    print(json.dumps(entry, indent=2))


def judged() -> None:
    """The acceptance of "the same optimum", from the results recorded."""
    from gemseo_lso.benchmarks.topology.split import acceptance

    results = json.loads(OUTPUT.read_text("utf-8"))
    entry = acceptance(
        results["agreement"]["max_relative_row_difference"],
        results["optimum"]["runs"],
    )
    save("acceptance", entry)
    print(json.dumps(entry, indent=2))


def main(arguments: list[str]) -> None:
    """Run what is asked for."""
    if arguments[:1] == ["one"]:
        kind, path, size = arguments[1], arguments[2], int(arguments[3])
        run = {"rows": rows_run, "iterations": iterations_run, "optimum": optimum_run}
        print(json.dumps(run[kind](path, size)))
        return
    steps = {
        "rows": rows_ladder,
        "iterations": iterations,
        "agreement": agreement,
        "optimum": optimum,
        "acceptance": judged,
    }
    for name in arguments or list(steps):
        steps[name]()


if __name__ == "__main__":
    main(sys.argv[1:])
