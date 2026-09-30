"""Measure the optimizer on the synthetic problem of local constraints.

Run it with: python plugins/gemseo_lso/benchmarks/run_synthetic.py [size ...]

For each size, GCMMA runs with the working set (rows computed at every
iteration, then young rows reused) and without it, then in the hybrid mode
(spec § 3.9): on the ring and on a 2D grid, colored at every iteration or every
three, and with a far coupling. The results are printed and written to
benchmarks/results/synthetic.json.
"""

import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import psutil

from gemseo_lso import Optimizer
from gemseo_lso import Settings
from gemseo_lso.benchmarks.synthetic import LocalConstraints

RESULTS = Path(__file__).parent / "results" / "synthetic.json"

REFERENCE_SIZE = 100_000
"""Every row is asked for up to this size only: it is the reference, and beyond
it each iteration asks for a million rows."""

VARIANTS: dict[str, tuple[dict[str, object], dict[str, object]]] = {
    "working set": ({}, {}),
    "working set, young rows reused": ({}, {"row_refresh": "near_active"}),
    "every row": (
        {},
        {
            "screening_margin": 1e9,
            "screening_margin_min": 1e9,
            "max_working_set": 10**9,
        },
    ),
    "hybrid": ({}, {"jacobian_mode": "hybrid"}),
    "hybrid, colored every 3 iterations": (
        {},
        {"jacobian_mode": "hybrid", "jacobian_refresh": 3},
    ),
    "hybrid, 2D grid": ({"grid": True}, {"jacobian_mode": "hybrid"}),
    "far coupling, working set": ({"coupling": 0.05}, {}),
    "far coupling, hybrid": ({"coupling": 0.05}, {"jacobian_mode": "hybrid"}),
}
"""The problem (beyond its size) and the settings of each variant."""


def peak_memory() -> float:
    """The peak memory of the process so far, in GB."""
    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None) or getattr(info, "rss", 0)
    return float(peak) / 1e9


def measure(size: int, variant: str) -> dict[str, object]:
    """One run."""
    options, changes = VARIANTS[variant]
    if options.get("grid"):
        size = int(np.sqrt(size)) ** 2
    problem = LocalConstraints(size, active_share=0.02, seed=0, **options)  # type: ignore[arg-type]
    settings = Settings(method="gcmma", **changes)  # type: ignore[arg-type]
    optimizer = Optimizer(problem, settings)
    start = time.perf_counter()
    reports = list(optimizer)
    elapsed = time.perf_counter() - start
    result = optimizer.result
    iterations = max(result.iterations, 1)
    return {
        "size": size,
        "variant": variant,
        "status": result.status,
        "iterations": result.iterations,
        "evaluations": result.evaluations,
        "error": float(np.abs(result.x - problem.solution).max()),
        "rows": problem.rows,
        "rows_per_iteration": problem.rows / iterations,
        "share_of_the_jacobian": problem.rows / (size * (result.iterations + 1)),
        "rows_reused": sum(report.rows_reused for report in reports),
        "directional_derivatives_per_iteration": problem.products / iterations,
        "repairs": sum(report.screening_repairs for report in reports),
        "largest_working_set": max(report.working_set for report in reports),
        "optimizer_seconds_per_iteration": sum(r.optimizer_time for r in reports)
        / iterations,
        "seconds": elapsed,
        "peak_memory_gb": peak_memory(),
    }


def main(sizes: list[int]) -> None:
    """Run every variant at every size; print and save the results."""
    runs = []
    for size in sizes:
        for variant in VARIANTS:
            if variant == "every row" and size > REFERENCE_SIZE:
                continue
            run = measure(size, variant)
            runs.append(run)
            print(
                f"{size:>9,} {variant:32s} {run['status']:9s} "
                f"it {run['iterations']:4d}  error {run['error']:.1e}  "
                f"rows/it {run['rows_per_iteration']:>10,.0f} "
                f"({run['share_of_the_jacobian']:.1%})  "
                f"directions/it {run['directional_derivatives_per_iteration']:>5,.0f}  "
                f"optimizer {run['optimizer_seconds_per_iteration']:.2f} s/it  "
                f"peak {run['peak_memory_gb']:.1f} GB",
                flush=True,
            )
    RESULTS.parent.mkdir(exist_ok=True)
    RESULTS.write_text(
        json.dumps(
            {
                "machine": {
                    "processor": platform.processor(),
                    "cores": psutil.cpu_count(),
                    "memory_gb": psutil.virtual_memory().total / 1e9,
                },
                "runs": runs,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main([int(size) for size in sys.argv[1:]] or [100_000, 1_000_000])
