"""Measure the performance targets of SPEC § 14.1 on a synthetic model.

Usage:
    python benchmarks/run.py [--model MODEL.gpb.json] [--scenario all] [--python-only]

Without ``--model``, the reference model (2,000 components, 50,000 variables,
6 levels, and a run of 50,000 samples) is generated in a temporary folder.

Two kinds of measurements:

- in this process, the pure Python parts: loading, resolution, validation,
  snapshot, N2 matrix;
- in the application, started in benchmark mode (``--benchmark``): the page
  opens the model and runs scripted scenarios (commands, validation round trip,
  canvas and N2 frame rates, auto-layout, results views). Its window must stay
  visible: hidden windows get fewer frames.

The measurements are printed and written to ``benchmarks/results/<date>.json``.
"""

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from generate import Settings
from generate import generate
from generate import write_run

from gemseo_process_builder.core.document import snapshot
from gemseo_process_builder.core.n2 import n2_matrix
from gemseo_process_builder.core.resolver import level_view
from gemseo_process_builder.core.resolver import resolve
from gemseo_process_builder.core.serialization import load_project
from gemseo_process_builder.core.serialization import save_project
from gemseo_process_builder.core.validation import ValidationContext
from gemseo_process_builder.core.validation import validate

RESULTS = Path(__file__).parent / "results"
GUI_TIMEOUT_S = 900


def timed(function: Callable[[], Any], repeats: int = 3) -> float:
    """The median duration of a function, in milliseconds."""
    durations = []
    for _ in range(repeats):
        start = time.perf_counter()
        function()
        durations.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(durations), 1)


def python_measurements(model: Path) -> dict[str, Any]:
    """The pure Python parts, measured in this process."""
    project = load_project(model)
    resolution = resolve(project)
    return {
        "load_ms": timed(lambda: load_project(model)),
        "resolve_ms": timed(lambda: resolve(project)),
        "validation_rules_ms": timed(
            lambda: validate(ValidationContext(project, resolution))
        ),
        "validation_full_ms": timed(
            lambda: validate(ValidationContext(project, resolve(project)))
        ),
        "snapshot_ms": timed(lambda: json.dumps(snapshot(project, 0))),
        "snapshot_kb": len(json.dumps(snapshot(project, 0))) // 1024,
        "level_view_big_ms": timed(lambda: level_view(resolution, project, "n-big")),
        "n2_root_ms": timed(lambda: n2_matrix(project, resolution, "n-root")),
    }


def gui_measurements(model: Path, scenario: str) -> dict[str, Any]:
    """The scenarios run by the application in benchmark mode."""
    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder) / "benchmark.json"
        command = [
            sys.executable,
            "-m",
            "gemseo_process_builder",
            str(model),
            "--benchmark",
            scenario,
            "--benchmark-output",
            str(output),
            "--preferences",
            str(Path(folder) / "preferences.json"),
        ]
        subprocess.run(command, check=False, timeout=GUI_TIMEOUT_S)
        if not output.exists():
            return {"error": "The application wrote no measurements."}
        return dict(json.loads(output.read_text(encoding="utf-8")))


def reference_model(folder: Path) -> Path:
    """Write the reference model of SPEC § 14.1 and its run of 50,000 samples."""
    model = folder / "synthetic.gpb.json"
    settings = Settings(samples=50_000)
    project = generate(settings)
    write_run(project, model, settings.samples, settings.seed)
    save_project(project, model)
    return model


def targets(python: dict[str, Any], gui: dict[str, Any]) -> list[tuple[str, str, str]]:
    """The § 14.1 targets with their measurements: (measure, target, value)."""

    def get(*keys: str) -> Any:
        value: Any = gui
        for key in keys:
            value = value.get(key, {}) if isinstance(value, dict) else {}
        return value if value != {} else "n/a"

    return [
        (
            "Project opening (page, until drawn)",
            "< 3000 ms",
            f"{get('open', 'total_ms')} ms",
        ),
        (
            "Editing command (round trip + render), p95",
            "< 100 ms",
            f"{get('command', 'p95_ms')} ms",
        ),
        (
            "Full static validation (Python)",
            "< 1000 ms",
            f"{python.get('validation_full_ms', 'n/a')} ms",
        ),
        (
            "Full static validation (from the page)",
            "< 1000 ms",
            f"{get('validation', 'median_ms')} ms",
        ),
        ("Canvas zoom, 300 nodes", ">= 30 fps", f"{get('canvas', 'zoom', 'fps')} fps"),
        ("Canvas pan, 300 nodes", ">= 30 fps", f"{get('canvas', 'pan', 'fps')} fps"),
        (
            "N2 2,000 x 2,000 scrolling",
            ">= 30 fps",
            f"{get('n2', 'scroll', 'fps')} fps",
        ),
        ("Auto-layout of 300 nodes", "< 2000 ms", f"{get('layout', 'duration_ms')} ms"),
        (
            "UI frames during auto-layout, max",
            "not blocked",
            f"{get('layout', 'frames_during_layout', 'max_ms')} ms",
        ),
    ]


def main() -> None:
    """Measure, print and record."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--scenario", default="all")
    parser.add_argument("--python-only", action="store_true")
    arguments = parser.parse_args()

    with tempfile.TemporaryDirectory() as folder:
        model = arguments.model or reference_model(Path(folder))
        python = python_measurements(model)
        gui = (
            {} if arguments.python_only else gui_measurements(model, arguments.scenario)
        )

    record = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpus": os.cpu_count(),
            "python": platform.python_version(),
        },
        "model": str(arguments.model or "reference (generated)"),
        "python": python,
        "gui": gui,
    }
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{datetime.now():%Y-%m-%d_%H%M%S}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"{'Measure':<46} {'Target':<12} Value")
    for measure, target, value in targets(python, gui):
        print(f"{measure:<46} {target:<12} {value}")
    print(f"\nAll measurements: {path}")


if __name__ == "__main__":
    main()
