"""The benchmark mode of the application (SPEC § 15.5).

``gemseo-process-builder --benchmark NAME --benchmark-output FILE PROJECT``
starts the application without opening the project: the page opens it
itself, runs the scripted scenario ``NAME`` (``static/js/services/benchmark.js``)
and reports its measurements, which are written to ``FILE`` before quitting.
"""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from PySide6.QtCore import QTimer

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.dialogs import UnsavedChoice

_LOGGER = logging.getLogger(__name__)


class UnattendedDialogs:
    """Dialogs answered without the user: a benchmark must never wait.

    Unsaved changes are discarded and autosaves are not recovered; errors are
    logged.
    """

    def ask_open_project(self) -> Path | None:
        """No file is chosen."""
        return None

    def ask_save_project(self, suggested_name: str) -> Path | None:
        """No file is chosen."""
        return None

    def ask_unsaved_changes(self, project_name: str) -> UnsavedChoice:
        """The changes are discarded."""
        return "discard"

    def ask_recover(self, project_name: str) -> bool:
        """The autosave is not recovered."""
        return False

    def ask_project_data(self, script_name: str, choices: list[str]) -> int | None:
        """No data is chosen."""
        return None

    def show_error(self, title: str, message: str) -> None:
        """The error is logged."""
        _LOGGER.error("%s: %s", title, message)


class ReportParams(BaseModel):
    """Parameters of ``benchmark.report``."""

    results: dict[str, Any]


def register_benchmark_methods(
    bridge: Bridge,
    scenario: str,
    project: Path,
    output: Path,
    quit_application: Callable[[], None],
) -> None:
    """Register ``benchmark.scenario`` and ``benchmark.report``.

    Args:
        bridge: The bridge of the page.
        scenario: The scenario to run, ``all`` for every one.
        project: The project the scenario opens.
        output: The JSON file receiving the measurements.
        quit_application: Called once the measurements are written.
    """

    def describe() -> dict[str, str]:
        return {"name": scenario, "project": str(project)}

    def report(params: ReportParams) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(params.results, indent=2), encoding="utf-8")
        _LOGGER.info("Benchmark %s written to %s", scenario, output)
        QTimer.singleShot(200, quit_application)

    bridge.registry.add("benchmark.scenario", describe)
    bridge.registry.add("benchmark.report", report)
