"""The stress-constrained bracket with a continuation on the parameters of its model.

Run it with:
    python plugins/gemseo_lso/benchmarks/run_continuation.py [variant] [size] [span]

``variant`` is ``penalty`` (the SIMP penalty from 1 to its value, 3, over the first
``span`` outer iterations), or ``penalty_radius`` (the radius of the density filter
too: from three times its value to its value). The optimizer and its settings are
those of ``run_piloted_topology.py``, without Claude: the run only asks whether a
design that starts convex, its load paths diffuse, ends on other load paths than
the one that goes straight from the full material, which fixes its structure by
the iteration 40 (90 % of the variables at a bound).

The results are written to ``benchmarks/results/continuation_<variant>/``.
"""

import logging
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from run_piloted_topology import build_scenario
from run_topology import save_design

from gemseo_claude_pilot.snapshots import database_entries
from gemseo_lso.benchmarks.topology.cases import l_bracket
from gemseo_lso.gemseo.live import forget
from gemseo_lso.gemseo.live import on_open

FOLDER = Path(__file__).parent / "results"


def main(variant: str = "penalty", size: int = 125, span: int = 40) -> None:
    """Run the bracket with the continuation, then to its end."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("gemseo").setLevel(logging.WARNING)
    problem = l_bracket(size)
    scenario = build_scenario(size, problem)
    penalty, radius = problem.penalty, problem.filter_radius
    changes: dict[str, Any] = {"penalty": 0, "radius": 0}
    optimization = scenario.formulation.optimization_problem
    first_true: dict[str, int] = {}
    """The evaluation the true parameters start at."""

    def apply(iteration: int) -> None:
        """The parameters after ``iteration`` outer iterations."""
        share = min(iteration / span, 1.0)
        problem.penalty = 1.0 + (penalty - 1.0) * share
        changes["penalty"] += 1
        if variant == "penalty_radius" and iteration % 2 == 0:
            problem.filter_radius = radius * (3.0 - 2.0 * share)
            problem.filter = problem._filter()
            changes["radius"] += 1
        # The finite-element state of the last point was computed with the old values.
        problem._state = None

    apply(0)  # The run starts on the convex problem.

    def follow(run: Any) -> None:
        def after(report: Any) -> None:
            if report.iteration <= span:
                apply(report.iteration)
            if report.iteration == span:
                # What the run met on the way was a feasible point of other problems:
                # its best feasible point is that of the true one, from here.
                first_true["n"] = len(optimization.database)
                state = run.optimizer.state  # type: ignore[union-attr]
                state.best_x, state.best_objective = None, float("inf")
            if report.iteration % 10 == 0:
                print(
                    f"iteration {report.iteration}: penalty {problem.penalty:.2f}, "
                    f"radius {problem.filter_radius:.2f}, volume "
                    f"{report.objective:.4f}, violation {report.max_constraint:.2e}",
                    flush=True,
                )

        run.watch(after)

    forget(problem)
    on_open(optimization, follow)
    start = time.perf_counter()
    scenario.execute(
        algo_name="LSO_MMA",
        max_iter=600,
        move_limit=0.2,
        ftol_rel=1e-4,
        row_batch_size=2000,
        log_problem=False,
    )
    elapsed = time.perf_counter() - start
    # Judged on the problem as it is at the end: the true penalty and radius, on the
    # points met since the parameters took their values.
    problem.penalty, problem.filter_radius = penalty, radius
    problem.filter = problem._filter()
    problem._state = None
    best: tuple[float, Any, float] | None = None
    for entry in database_entries(optimization)[first_true.get("n", 0) :]:
        x = np.asarray(entry[0], dtype=float)
        volume, constraints, _ = problem.values(x)
        violation = float(np.max(constraints))
        if violation <= 1e-4 and (best is None or volume < best[0]):
            best = (volume, x, violation)
    if best is None:
        print(f"{variant}: no feasible point after the continuation")
        return
    volume, x_best, violation = best
    stresses = problem.stresses(x_best)
    folder = FOLDER / f"continuation_{variant}"
    folder.mkdir(parents=True, exist_ok=True)
    np.save(folder / "design.npy", x_best)
    save_design(problem, x_best, folder / "design.png")
    print(
        f"{variant}: {elapsed:.0f} s, volume {volume:.4f}, largest stress "
        f"{stresses.max() / problem.stress_limit:.4f} of the limit, "
        f"{changes['penalty']} changes of the penalty, "
        f"{changes['radius']} of the radius"
    )


if __name__ == "__main__":
    main(
        sys.argv[1] if len(sys.argv) > 1 else "penalty",
        *(int(item) for item in sys.argv[2:4]),
    )
