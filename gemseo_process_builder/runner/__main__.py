"""The runner: ``python -m gemseo_process_builder.runner <run folder>`` (SPEC § 11).

It imports ``script.py`` from the run folder, builds what the script runs,
attaches the instrumentation, runs it, saves the outputs into the run folder
and reports everything as JSON-lines events on its protected standard output.
It never calls the script's ``main()``.
"""

import importlib.metadata
import importlib.util
import json
import logging
import math
import os
import platform
import sys
import threading
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any

from gemseo_process_builder.runner.instrumentation import LogForwarder
from gemseo_process_builder.runner.instrumentation import ProblemListener
from gemseo_process_builder.runner.instrumentation import observe_disciplines
from gemseo_process_builder.runner.instrumentation import observe_nested_scenarios
from gemseo_process_builder.runner.instrumentation import plain
from gemseo_process_builder.runner.instrumentation import top_disciplines
from gemseo_process_builder.runner.rate_limiter import RateLimiter
from gemseo_process_builder.runner.stop import RunStopped
from gemseo_process_builder.runner.stop import StopFlag
from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.protocol import protected_stdin

FLUSH_INTERVAL_S = 0.5


def load_script(folder: Path) -> tuple[ModuleType, dict[str, Any]]:
    """Import ``script.py`` and read its mapping sidecar."""
    mapping = json.loads((folder / "script.gpb-map.json").read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("script", folder / "script.py")
    if spec is None or spec.loader is None:  # pragma: no cover - a .py file
        msg = "The script cannot be loaded."
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules["script"] = module
    spec.loader.exec_module(module)
    return module, mapping


def prepare_gemseo(validate_data: bool = True) -> None:
    """Let GEMSEO notify the status of disciplines, and log through the runner.

    GEMSEO writes its log to the standard error; the runner already sends it
    as ``log`` events, so GEMSEO's own stream handlers are removed.

    Args:
        validate_data: Whether GEMSEO checks the data the disciplines exchange
            (off in the fast mode of a driver). ``configure`` sets every
            option, so they are set together.
    """
    if "gemseo" not in sys.modules:  # A script without GEMSEO (protocol tests).
        return
    from gemseo import configure

    configure(
        enable_discipline_status=True,
        validate_input_data=validate_data,
        validate_output_data=validate_data,
    )
    gemseo_logger = logging.getLogger("gemseo")
    for handler in list(gemseo_logger.handlers):
        if isinstance(handler, logging.StreamHandler):
            gemseo_logger.removeHandler(handler)
    gemseo_logger.propagate = True


class Run:
    """One run of a script, reporting to an event channel."""

    def __init__(self, folder: Path, limiter: RateLimiter, stop: StopFlag) -> None:
        self.folder = folder
        self.limiter = limiter
        self.stop = stop
        self.scenario: Any = None
        self.listener: ProblemListener | None = None

    def execute(self) -> dict[str, Any]:
        """Run the script; return the summary of the results."""
        module, mapping = load_script(self.folder)
        prepare_gemseo(bool(mapping.get("validate_data", True)))
        if mapping.get("kind") == "scenario":
            return self._run_scenario(module, mapping)
        return self._run_process(module, mapping)

    def _run_scenario(
        self, module: ModuleType, mapping: dict[str, Any]
    ) -> dict[str, Any]:
        self.scenario = module.build_scenario()
        progress = mapping.get("progress", {})
        processes = int(mapping.get("n_processes", 1))
        self.listener = ProblemListener(
            self.scenario.formulation.optimization_problem,
            self.limiter,
            self.stop,
            progress.get("unit", "iteration"),
            progress.get("total"),
            processes,
        )
        disciplines = top_disciplines(self.scenario)
        if processes == 1:
            # With several processes, the disciplines run in the child processes.
            observe_disciplines(disciplines, mapping, self.limiter, self.stop)
            observe_nested_scenarios(disciplines, mapping, self.limiter, self.stop)
        module.execute_scenario(self.scenario)
        return {}

    def _run_process(
        self, module: ModuleType, mapping: dict[str, Any]
    ) -> dict[str, Any]:
        process = module.build_process()
        observe_disciplines([process], mapping, self.limiter, self.stop)
        observe_nested_scenarios([process], mapping, self.limiter, self.stop)
        self.stop.check()
        outputs = process.execute()
        results = {name: plain(value) for name, value in outputs.items()}
        path = self.folder / "results.json"
        path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        return {"outputs": results}

    def _scenario_summary(self) -> dict[str, Any]:
        """Evaluations, and the optimum when GEMSEO found one."""
        if self.scenario is None:
            return {}
        problem = self.scenario.formulation.optimization_problem
        summary: dict[str, Any] = {
            "n_evaluations": len(problem.database),
            "objective": problem.objective.name,
        }
        result = getattr(self.scenario, "optimization_result", None)
        if result is not None and getattr(result, "f_opt", None) is not None:
            summary["best_objective"] = plain(result.f_opt)
            summary["is_feasible"] = bool(getattr(result, "is_feasible", True))
            x_opt = problem.design_space.convert_array_to_dict(result.x_opt)
            summary["x_opt"] = {name: plain(value) for name, value in x_opt.items()}
            database = problem.database
            summary["constraints"] = {
                c.name: plain(database.get_function_value(c.name, result.x_opt))
                for c in problem.constraints
            }
        return summary

    def variables(self) -> list[dict[str, Any]]:
        """The variables of the results, with their roles."""
        if self.scenario is None:
            return []
        problem = self.scenario.formulation.optimization_problem
        is_doe = self.listener is not None and self.listener.unit == "sample"
        space = problem.design_space
        variables = [
            {
                "name": name,
                "size": space.variable_sizes[name],
                "role": "design variable",
                "lower": finite(space.get_lower_bound(name)),
                "upper": finite(space.get_upper_bound(name)),
            }
            for name in space.variable_names
        ]
        role = "output" if is_doe else "objective"
        variables.append({"name": problem.objective.name, "role": role})
        variables += [
            {"name": c.name, "role": "constraint", "constraint_type": c.f_type}
            for c in problem.constraints
        ]
        role = "output" if is_doe else "observable"
        variables += [{"name": o.name, "role": role} for o in problem.observables]
        return variables

    def save_outputs(self) -> None:
        """Save the history and the dataset of the scenario, even partial."""
        if self.listener is not None:
            self.listener.report_pending()
        if self.scenario is None:
            return
        problem = self.scenario.formulation.optimization_problem
        if not len(problem.database):
            return
        import numpy as np

        logging.getLogger(__name__).info("Saving the history and the dataset")
        self.scenario.save_optimization_history(self.folder / "history.h5")
        # Much faster than scenario.to_dataset() on long histories.
        dataset = problem.database.to_dataset()
        dataset.to_csv(self.folder / "dataset.csv")
        # The same values in binary, column by column: reading the CSV of a run
        # with thousands of variables takes seconds, this file a fraction.
        values = dataset.to_numpy(dtype=float, na_value=np.nan)
        np.save(self.folder / "dataset.npy", np.asfortranarray(values))


def finite(values: Any) -> list[float | None]:
    """Bounds as JSON numbers; infinite bounds become ``None``."""
    return [None if math.isinf(value) else float(value) for value in values]


def versions() -> dict[str, str]:
    """The versions of Python and, when the script used it, of GEMSEO."""
    found = {"python": platform.python_version()}
    if "gemseo" in sys.modules:
        found["gemseo"] = importlib.metadata.version("gemseo")
    return found


def main(argv: list[str] | None = None) -> int:
    """Run the script of a run folder; the exit code tells whether it completed."""
    arguments = sys.argv[1:] if argv is None else argv
    folder = Path(arguments[0]).resolve()
    channel = EventChannel()
    commands = protected_stdin()
    stop = StopFlag()
    stop.listen(commands)
    limiter = RateLimiter(channel.event)
    handler = LogForwarder(limiter)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    finished = threading.Event()

    def flush_regularly() -> None:
        while not finished.wait(FLUSH_INTERVAL_S):
            limiter.flush()

    threading.Thread(target=flush_regularly, name="flush", daemon=True).start()
    os.chdir(folder)  # Relative paths of the script refer to the run folder.
    sys.path.insert(0, str(folder))
    channel.event("started", {"run_id": folder.name, "pid": os.getpid()})
    run = Run(folder, limiter, stop)
    payload: dict[str, Any]
    try:
        summary = run.execute()
        payload = {"state": "completed", "summary": summary}
    except RunStopped:
        payload = {"state": "stopped", "summary": {}}
    except BaseException as error:  # Report any failure, even SystemExit.
        payload = {
            "state": "failed",
            "summary": {},
            "error": f"{type(error).__name__}: {error}",
            "traceback": traceback.format_exc(),
        }
    try:
        run.save_outputs()
        if run.scenario is not None:
            payload["summary"] = {**payload["summary"], **run._scenario_summary()}
            payload["variables"] = run.variables()
    except Exception as error:  # The outputs are secondary: keep the state.
        logging.getLogger(__name__).warning("The outputs could not be saved: %s", error)
    payload["versions"] = versions()
    finished.set()
    limiter.flush()
    logging.getLogger().removeHandler(handler)
    channel.event("finished", payload)
    return 0 if payload["state"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
