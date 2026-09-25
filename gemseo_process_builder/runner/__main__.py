"""The runner: ``python -m gemseo_process_builder.runner <run folder>`` (SPEC § 11).

It imports ``script.py`` from the run folder, builds what the script runs,
attaches the instrumentation, runs it, saves the outputs into the run folder
and reports everything as JSON-lines events on its protected standard output.
It never calls the script's ``main()``.
"""

import importlib.util
import json
import logging
import os
import sys
import threading
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any

from gemseo_process_builder.runner.instrumentation import LogForwarder
from gemseo_process_builder.runner.instrumentation import ProblemListener
from gemseo_process_builder.runner.instrumentation import observe_disciplines
from gemseo_process_builder.runner.instrumentation import plain
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


def prepare_gemseo() -> None:
    """Let GEMSEO notify the status of disciplines, and log through the runner.

    GEMSEO writes its log to the standard error; the runner already sends it
    as ``log`` events, so GEMSEO's own stream handlers are removed.
    """
    if "gemseo" not in sys.modules:  # A script without GEMSEO (protocol tests).
        return
    from gemseo import configure

    configure(enable_discipline_status=True)
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
        prepare_gemseo()
        if mapping.get("kind") == "scenario":
            return self._run_scenario(module, mapping)
        return self._run_process(module, mapping)

    def _run_scenario(
        self, module: ModuleType, mapping: dict[str, Any]
    ) -> dict[str, Any]:
        self.scenario = module.build_scenario()
        progress = mapping.get("progress", {})
        self.listener = ProblemListener(
            self.scenario.formulation.optimization_problem,
            self.limiter,
            self.stop,
            progress.get("unit", "iteration"),
            progress.get("total"),
        )
        observe_disciplines(self.scenario.disciplines, mapping, self.limiter, self.stop)
        module.execute_scenario(self.scenario)
        return self._scenario_summary()

    def _run_process(
        self, module: ModuleType, mapping: dict[str, Any]
    ) -> dict[str, Any]:
        process = module.build_process()
        observe_disciplines([process], mapping, self.limiter, self.stop)
        self.stop.check()
        outputs = process.execute()
        results = {name: plain(value) for name, value in outputs.items()}
        path = self.folder / "results.json"
        path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        return {"outputs": results}

    def _scenario_summary(self) -> dict[str, Any]:
        result = getattr(self.scenario, "optimization_result", None)
        if result is None or getattr(result, "f_opt", None) is None:
            return {}
        return {
            "f_opt": plain(result.f_opt),
            "x_opt": plain(result.x_opt),
            "is_feasible": bool(getattr(result, "is_feasible", True)),
        }

    def save_outputs(self) -> None:
        """Save the history and the dataset of the scenario, even partial."""
        if self.listener is not None:
            self.listener.report_pending()
        if self.scenario is None:
            return
        problem = self.scenario.formulation.optimization_problem
        if not len(problem.database):
            return
        logging.getLogger(__name__).info("Saving the history and the dataset")
        self.scenario.save_optimization_history(self.folder / "history.h5")
        # Much faster than scenario.to_dataset() on long histories.
        problem.database.to_dataset().to_csv(self.folder / "dataset.csv")


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
    except Exception as error:  # The outputs are secondary: keep the state.
        logging.getLogger(__name__).warning("The outputs could not be saved: %s", error)
    finished.set()
    limiter.flush()
    logging.getLogger().removeHandler(handler)
    channel.event("finished", payload)
    return 0 if payload["state"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
