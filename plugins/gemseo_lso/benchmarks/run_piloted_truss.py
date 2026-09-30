"""The 10-bar truss, with and without the descent, piloted by Claude.

Run it with:
    python plugins/gemseo_lso/benchmarks/run_piloted_truss.py [descent] [delay]

The 10-bar truss (Schmit and Farshi: optimum 5060.85 lb, and a local optimum at
5076.85 lb) as a GEMSEO scenario, ``LSO_GCMMA`` with the Claude copilot in
``pilot`` mode (needs ``gemseo-claude-pilot`` and Claude Code logged in). Claude
is called after the first iteration, then every 3 iterations, and answers in the
background. The truss is solved in a fraction of a second, faster than Claude
answers: ``delay`` seconds are added to each iteration (each gradient), to stand for a
costly simulation. The journal of the copilot goes to ``results/piloted_truss/``.
"""

import logging
import sys
import time
from collections.abc import Iterable
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from gemseo import create_design_space
from gemseo import create_scenario
from gemseo.core.discipline import Discipline

from gemseo_claude_pilot import ClaudePilot
from gemseo_claude_pilot.budget import Budget
from gemseo_claude_pilot.triggers import TriggerSettings
from gemseo_lso.benchmarks.literature.trusses import ten_bar

FOLDER = Path(__file__).parent / "results" / "piloted_truss"


class TrussDiscipline(Discipline):  # type: ignore[misc]
    """The weight and the constraints (``value / limit - 1``) of the truss."""

    def __init__(self, delay: float = 0.0) -> None:
        super().__init__("Truss")
        self.delay = delay
        self.truss = ten_bar()
        self.problem = self.truss.problem(0.5)
        size = self.problem.x0.size
        rows = self.problem.values(self.problem.x0)[1].size
        self.io.input_grammar.update_from_data({"x": self.problem.x0.copy()})
        self.io.output_grammar.update_from_data(
            {"weight": np.zeros(1), "constraints": np.zeros(rows)}
        )
        self.io.input_grammar.defaults = {"x": np.full(size, 0.5)}

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        weight, constraints, _ = self.problem.values(input_data["x"])
        return {"weight": np.array([weight]), "constraints": constraints}

    def _compute_jacobian(
        self, input_names: Iterable[str] = (), output_names: Iterable[str] = ()
    ) -> None:
        # One gradient per iteration: the delay stands for the simulation.
        time.sleep(self.delay)
        x = self.io.data["x"]
        rows = np.arange(self.problem.values(x)[1].size)
        self.jac = {
            "weight": {"x": self.problem.objective_gradient(x)[None, :]},
            "constraints": {"x": self.problem.constraint_rows(x, rows)},
        }


def main(descent_iterations: int = 0, delay: float = 0.0) -> None:
    """Run the piloted truss."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("gemseo").setLevel(logging.WARNING)
    discipline = TrussDiscipline(delay)
    space = create_design_space()
    space.add_variable("x", size=10, lower_bound=0.0, upper_bound=1.0, value=0.5)
    scenario = create_scenario(
        [discipline], "weight", space, formulation_name="DisciplinaryOpt"
    )
    scenario.add_constraint("constraints", "ineq")
    FOLDER.mkdir(parents=True, exist_ok=True)
    pilot = ClaudePilot(
        mode="pilot",
        journal=FOLDER / f"journal_descent{descent_iterations}_delay{delay:g}.jsonl",
        triggers=TriggerSettings(
            period=None,
            period_iterations=3,
            answer_pause=0.0,
            min_interval=0.0,
            start=False,
        ),
        report=lambda: False,
        budget=Budget(max_calls=20, max_tokens=2_000_000),
    )
    start = time.perf_counter()
    result = pilot.execute(
        scenario,
        "LSO_GCMMA",
        max_iter=100,
        descent_iterations=descent_iterations,
        log_problem=False,
    )
    elapsed = time.perf_counter() - start
    optimization = scenario.formulation.optimization_problem
    x_best = optimization.design_space.get_current_value()
    truss = discipline.truss
    areas = truss.areas(x_best)
    print(
        f"descent_iterations={descent_iterations}: {elapsed:.0f} s, "
        f"weight {truss.weight(areas):.3f} lb (5060.85 published), "
        f"worst constraint {truss.worst(areas):+.1e}, "
        f"{discipline.problem.evaluations} evaluations, "
        f"{len(result.decisions)} decisions of Claude, stop: {result.stop_reason}"
    )


if __name__ == "__main__":
    main(
        int(sys.argv[1]) if len(sys.argv) > 1 else 0,
        float(sys.argv[2]) if len(sys.argv) > 2 else 0.0,
    )
