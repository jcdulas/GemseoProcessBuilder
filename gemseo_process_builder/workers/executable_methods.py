"""Test runs of executable wrappers from their editor (runs in the worker)."""

import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import ValidationError

from gemseo_process_builder.runtime.spec import ExecutableSpec
from gemseo_process_builder.workers.gemseo_loader import require_gemseo
from gemseo_process_builder.workers.server import RequestContext
from gemseo_process_builder.workers.server import WorkerError


def _plain(value: Any) -> Any:
    return value.tolist() if hasattr(value, "tolist") else value


def test_run(
    spec_data: dict[str, Any], inputs: dict[str, Any], base_folder: str
) -> dict[str, Any]:
    """Run a wrapper once and report everything the editor shows.

    The working folder is kept, so that the user can look at it.

    Returns:
        ``outputs`` (by name), ``error`` (empty when the run succeeded), the
        ``command``, ``returncode``, ``stdout``, ``stderr`` and ``workdir``.
    """
    require_gemseo()
    from gemseo_process_builder.runtime.executable import ExecutableDiscipline
    from gemseo_process_builder.runtime.executable import ExecutableError

    try:
        spec = ExecutableSpec.model_validate(spec_data)
    except ValidationError as error:
        raise WorkerError("invalid_params", f"Invalid wrapper: {error}") from None
    spec = spec.model_copy(
        update={
            "retention": "always",
            "workdir_root": spec.workdir_root or tempfile.gettempdir(),
        }
    )
    discipline = ExecutableDiscipline(spec, Path(base_folder or "."))
    text_inputs = {port.name for port in spec.inputs if port.dtype in ("str", "path")}
    data = {
        name: value if name in text_inputs else np.atleast_1d(np.asarray(value, float))
        for name, value in inputs.items()
    }
    report: dict[str, Any] = {"outputs": {}, "error": ""}
    try:
        outputs = discipline.execute(data)
        report["outputs"] = {
            port.name: _plain(outputs[port.name])
            for port in spec.outputs
            if port.name in outputs
        }
    except (ExecutableError, ValueError, KeyError) as error:
        report["error"] = str(error)
    run = discipline.last_run
    report.update(
        {
            "command": run.args if run else discipline.command_line(Path("<workdir>")),
            "returncode": run.returncode if run else None,
            "stdout": run.stdout[-20000:] if run else "",
            "stderr": run.stderr[-20000:] if run else "",
            "workdir": str(discipline.last_workdir or ""),
        }
    )
    return report


def _test_run(params: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    return test_run(
        dict(params.get("spec") or {}),
        dict(params.get("inputs") or {}),
        str(params.get("base_folder") or ""),
    )


def register(server: Any) -> None:
    """Add the executable wrapper methods to the worker."""
    server.add("executable.test_run", _test_run)
