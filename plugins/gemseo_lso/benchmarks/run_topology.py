"""Measure the optimizer on stress-constrained topology optimization (plan 69).

Run it with:
    python plugins/gemseo_lso/benchmarks/run_topology.py <variant> [<variant> ...]

The variants are listed in ``VARIANTS``; each run is appended to
``benchmarks/results/topology.json`` and its final design saved as
``benchmarks/results/topology_<variant>.png``. The L-shaped bracket of about
10⁴ elements (125 across) is the reference size; ``fine`` runs about 10⁵
elements (400 across), started from the design of ``screened`` interpolated
on the fine grid.
"""

import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import psutil

from gemseo_lso import Optimizer
from gemseo_lso import Settings
from gemseo_lso.benchmarks.topology.cases import l_bracket
from gemseo_lso.benchmarks.topology.model import StressTopology
from gemseo_lso.core.sparse_jacobian import probe_sparsity

RESULTS = Path(__file__).parent / "results"
COARSE = 125
"""Elements across the bracket: 10,000 elements."""

FINE = 400
"""102,400 elements."""

BASE = Settings(
    method="mma",
    move_limit=0.2,
    max_iter=200,
    ftol_rel=1e-4,
    stall_iterations=5,
    row_batch_size=2000,
)
"""MMA with a move limit of 0.2, stopped when the volume changes less than 1e-4
over 5 iterations (a KKT residual of 1e-3 is out of reach: stress-constrained
designs keep oscillating a little at the reentrant corner)."""

EVERY_ROW = {
    "screening_margin": 1e9,
    "screening_margin_min": 1e9,
    "max_working_set": 10**9,
}

COLORED = {"pattern_margin": 0, "color_overlap": 2}
"""Colorings of the pattern itself, then widened once: 25 and 249 colors at a
radius of 1 element; a margin of 1 gives 479 and 1,200 at a radius of 2."""

VARIANTS: dict[str, tuple[float | None, dict[str, Any]]] = {
    "screened": (None, {}),
    "reference": (None, EVERY_ROW),
    "near_active": (None, {"row_refresh": "near_active"}),
    "gcmma": (None, {"method": "gcmma"}),
    "hybrid": (1.0, {"jacobian_mode": "hybrid", **COLORED}),
}
"""The radius of the pattern (if not the case's) and the settings of each run
of the optimizer, beyond ``BASE``."""


def peak_memory() -> float:
    """The peak memory of the process so far, in GB."""
    info = psutil.Process().memory_info()
    return float(getattr(info, "peak_wset", None) or info.rss) / 1e9


def save_design(problem: StressTopology, x: np.ndarray, path: Path) -> None:
    """The filtered densities of the grid, as an image."""
    import matplotlib as mpl

    mpl.use("Agg")
    import matplotlib.pyplot as plt

    image = np.full(problem.mask.shape, np.nan)
    image[problem.mask] = problem.filter @ x
    figure, axes = plt.subplots(figsize=(5, 5))
    axes.imshow(image, origin="lower", cmap="gray_r", vmin=0, vmax=1)
    axes.set_axis_off()
    figure.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(figure)


def record(entry: dict[str, Any]) -> None:
    """Append a run to the results and print it."""
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / "topology.json"
    runs = json.loads(path.read_text("utf-8")) if path.is_file() else []
    runs = [run for run in runs if run["variant"] != entry["variant"]] + [entry]
    path.write_text(json.dumps(runs, indent=2), "utf-8")
    print(json.dumps(entry), flush=True)


def run_lso(name: str, problem: StressTopology, settings: Settings) -> np.ndarray:
    """One run of the optimizer on the problem; the final design."""
    optimizer = Optimizer(problem, settings)
    start = time.perf_counter()
    reports = []
    for report in optimizer:
        reports.append(report)
        if report.iteration % 10 == 0:
            print(
                f"{name} it {report.iteration} volume {report.objective:.4f} "
                f"max {report.max_constraint:+.2e} working set {report.working_set} "
                f"optimizer {report.optimizer_time:.1f} s "
                f"model {report.model_time:.1f} s",
                flush=True,
            )
    result = optimizer.result
    iterations = max(result.iterations, 1)
    stresses = problem.stresses(result.x)
    record(
        {
            "variant": name,
            "elements": problem.elements,
            "status": result.status,
            "iterations": result.iterations,
            "evaluations": problem.evaluations,
            "volume": result.objective,
            "max_stress_ratio": float(stresses.max() / problem.stress_limit),
            "rows": problem.rows,
            "rows_per_iteration": problem.rows / iterations,
            "rows_reused": sum(r.rows_reused for r in reports),
            "directional_derivatives": problem.products,
            "repairs": sum(r.screening_repairs for r in reports),
            "largest_working_set": max(r.working_set for r in reports),
            "optimizer_seconds": sum(r.optimizer_time for r in reports),
            "model_seconds": sum(r.model_time for r in reports),
            "seconds": time.perf_counter() - start,
            "seconds_per_iteration": (time.perf_counter() - start) / iterations,
            "peak_memory_gb": peak_memory(),
            "volume_history": [r.objective for r in reports],
        }
    )
    save_design(problem, result.x, RESULTS / f"topology_{name}.png")
    return result.x


def run_nlopt() -> None:
    """NLOPT_MMA on a p-norm of the stresses: one constraint in place of 10⁴."""
    import logging

    from gemseo import create_design_space
    from gemseo import create_scenario

    from gemseo_lso.benchmarks.topology.disciplines import AggregatedStressDiscipline

    logging.getLogger("gemseo").setLevel(logging.WARNING)
    problem = l_bracket(COARSE)
    discipline = AggregatedStressDiscipline(problem)
    space = create_design_space()
    space.add_variable(
        "x", size=problem.elements, lower_bound=0.0, upper_bound=1.0, value=1.0
    )
    scenario = create_scenario(
        [discipline], "volume", space, formulation_name="DisciplinaryOpt"
    )
    scenario.add_constraint("stress_norm", "ineq")
    start = time.perf_counter()
    scenario.execute(
        algo_name="NLOPT_MMA", max_iter=BASE.max_iter, ftol_rel=1e-4, log_problem=False
    )
    elapsed = time.perf_counter() - start
    result = scenario.optimization_result
    stresses = problem.stresses(result.x_opt)
    record(
        {
            "variant": "nlopt_mma_pnorm",
            "elements": problem.elements,
            "status": result.message,
            "evaluations": problem.evaluations,
            "volume": float(result.f_opt),
            "max_stress_ratio": float(stresses.max() / problem.stress_limit),
            "adjoint_solves": problem.solves,
            "seconds": elapsed,
            "peak_memory_gb": peak_memory(),
        }
    )
    save_design(problem, result.x_opt, RESULTS / "topology_nlopt_mma_pnorm.png")


def run_probe() -> None:
    """Measure how local the stress rows are.

    The share of the exact rows outside a pattern, by radius, and the error of
    the colored entries for the radii whose coloring is affordable; on 40
    elements of the structure (densities above 0.5).
    """
    design = RESULTS / "topology_screened.npy"
    points = {"full": l_bracket(COARSE).x0}
    if design.is_file():
        points["optimized"] = np.load(design)
    for label, x in points.items():
        solid = np.flatnonzero(l_bracket(COARSE).filter @ x > 0.5)
        rows = solid[np.linspace(0, solid.size - 1, 40).astype(int)]
        exact = l_bracket(COARSE).constraint_rows(x, rows)
        norms = np.linalg.norm(exact, axis=1)
        for radius in (1.0, 2.0, 3.0, 6.0, 12.0, 24.0):
            problem = replace(l_bracket(COARSE), radius=radius)
            inside = problem.sparsity()[rows].toarray()
            outside = np.linalg.norm(np.where(inside, 0.0, exact), axis=1) / norms
            entry: dict[str, Any] = {
                "variant": f"probe_radius_{radius:g}_{label}",
                "elements": problem.elements,
                "radius": radius,
                "pattern_per_row": float(inside.sum(axis=1).mean()),
                "outside_median": float(np.median(outside)),
                "outside_max": float(outside.max()),
            }
            if radius <= 3:
                start = time.perf_counter()
                probe = probe_sparsity(problem, x, rows, replace(BASE, **COLORED))
                entry.update(
                    colors=probe.colors,
                    error_median=float(np.median(probe.error)),
                    leakage_median=float(np.median(probe.leakage)),
                    seconds=time.perf_counter() - start,
                )
            record(entry)


def run_fine() -> None:
    """About 10⁵ elements, from the design of ``screened`` on the finer grid."""
    coarse = l_bracket(COARSE)
    design = np.load(RESULTS / "topology_screened.npy")
    problem = l_bracket(FINE)
    # The element of the coarse grid under the center of each fine element.
    scale = COARSE / FINE
    image = np.full(coarse.mask.shape, 0.0)
    image[coarse.mask] = design
    columns = np.minimum((problem.centers[:, 0] * scale).astype(int), COARSE - 1)
    rows = np.minimum((problem.centers[:, 1] * scale).astype(int), COARSE - 1)
    problem._x0 = image[rows, columns]
    settings = replace(
        BASE, max_iter=20, row_batch_size=1000, restoration_iterations=10
    )
    run_lso("fine", problem, settings)


def main(names: list[str]) -> None:
    """Run the variants asked for."""
    for name in names:
        if name == "nlopt":
            run_nlopt()
        elif name == "probe":
            run_probe()
        elif name == "fine":
            run_fine()
        else:
            radius, changes = VARIANTS[name]
            problem = l_bracket(COARSE)
            if radius is not None:
                problem = replace(problem, radius=radius)
            x = run_lso(name, problem, replace(BASE, **changes))
            if name == "screened":
                np.save(RESULTS / "topology_screened.npy", x)


if __name__ == "__main__":
    main(sys.argv[1:] or ["screened"])
