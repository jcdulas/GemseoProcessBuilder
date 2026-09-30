"""The stress-constrained bracket piloted by Claude (plan 70, acceptance by hand).

Run it with:
    python plugins/gemseo_lso/benchmarks/run_piloted_topology.py [size] [mode]

The L-shaped bracket of about ``0.64 size²`` elements (125 across by default:
10⁴ elements) as a GEMSEO scenario: the stresses of the working set by adjoint
(``RowJacobian``), ``LSO_MMA``, the Claude copilot in ``pilot`` mode (or
``advisor``, ``observer``) with the user's Claude Code. Claude sees the report
of each outer iteration, and its changes of settings apply at the next one.
The bracket describes its physics (plan 71): Claude reads maps of the design
and its physical indicators when the run is stuck, and may restart it from a
transformed design. The density map and the indicators of the result are
printed at the end.
Claude answers in the background: the study waits for it only if asked, at
the start (a review of the problem before the run) and at the end (the report
of the run). The journal of the copilot, its report and the final design are
written to ``benchmarks/results/piloted/``.

Needs ``gemseo-claude-pilot`` installed and Claude Code logged in; without
them, the scenario runs as is.
"""

import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
from gemseo import create_design_space
from gemseo import create_scenario

from gemseo_claude_pilot import ClaudePilot
from gemseo_claude_pilot.budget import Budget
from gemseo_claude_pilot.design import DesignSource
from gemseo_claude_pilot.design import indicators
from gemseo_claude_pilot.snapshots import database_entries
from gemseo_claude_pilot.snapshots import snapshot_problem
from gemseo_claude_pilot.triggers import TriggerSettings
from gemseo_lso.benchmarks.topology.cases import l_bracket
from gemseo_lso.benchmarks.topology.disciplines import StressDiscipline

FOLDER = Path(__file__).parent / "results" / "piloted"


def ask(question: str) -> bool:
    """A yes-or-no question in the terminal; no when nobody can answer."""
    if not sys.stdin.isatty():
        return False
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:  # A terminal with nothing to read: nobody answers.
        return False


def main(size: int = 125, mode: str = "pilot") -> None:
    """Run the piloted bracket."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("gemseo").setLevel(logging.WARNING)
    problem = l_bracket(size)
    space = create_design_space()
    space.add_variable(
        "x", size=problem.elements, lower_bound=0.0, upper_bound=1.0, value=1.0
    )
    scenario = create_scenario(
        [StressDiscipline(problem)], "volume", space, formulation_name="DisciplinaryOpt"
    )
    scenario.add_constraint("stress", "ineq")
    pilot = ClaudePilot(
        mode=mode,  # type: ignore[arg-type]
        journal=FOLDER / "journal.jsonl",
        # Claude is called every 10 outer iterations, or at the first one
        # 10 seconds after its last answer: Claude Opus 5.5 at a low effort
        # answers in seconds to a minute, and follows the run nearly all the
        # time. It answers in the background: only the review before the run
        # and the report after it make the study wait, if asked.
        triggers=TriggerSettings(
            period=None,
            period_iterations=10,
            answer_pause=10.0,
            min_interval=0.0,
            start=ask("Should Claude review the problem before the run?"),
        ),
        report=lambda: ask("Should Claude write the report of the run?"),
        # Called this often, Claude needs more than the default 30 calls.
        budget=Budget(max_calls=300, max_tokens=10_000_000),
    )
    start = time.perf_counter()
    result = pilot.execute(
        scenario,
        "LSO_MMA",
        max_iter=600,
        move_limit=0.2,
        ftol_rel=1e-4,
        row_batch_size=2000,
        log_problem=False,
    )
    elapsed = time.perf_counter() - start
    # The pilot leaves the best point of the whole run in the design space;
    # GEMSEO has no result when Claude ended the last segment.
    optimization = scenario.formulation.optimization_problem
    x_best = optimization.design_space.get_current_value()
    volume = float(optimization.database.get_function_value("volume", x_best))
    stresses = problem.stresses(x_best)
    print(
        f"{elapsed:.0f} s, volume {volume:.4f}, "
        f"largest stress {stresses.max() / problem.stress_limit:.4f} of the limit, "
        f"{problem.rows} rows, {len(result.decisions)} decisions of Claude, "
        f"stop: {result.stop_reason}"
    )
    FOLDER.mkdir(parents=True, exist_ok=True)
    np.save(FOLDER / "design.npy", x_best)
    snapshot = snapshot_problem(optimization, "LSO_MMA", 600)
    source = DesignSource.find(scenario, snapshot)
    if source is not None:
        view = source.view(database_entries(optimization), snapshot)
        point = view.main_point()
        if point is not None:
            print(view.text_map(view.density_name(point), point))
            print(json.dumps(indicators(view, point), indent=1))


if __name__ == "__main__":
    main(*(int(sys.argv[1]),) if len(sys.argv) > 1 else (), *sys.argv[2:3])
