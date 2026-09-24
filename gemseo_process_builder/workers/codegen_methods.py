"""Dry run of generated scripts (runs in the worker; SPEC § 9.2).

The script is imported from a temporary file and its scenario (or process)
is built, without being executed: GEMSEO checks the disciplines, the design
space, the objectives and the constraints on the way.
"""

import importlib.util
import re
import sys
import tempfile
import traceback
import uuid
from pathlib import Path
from typing import Any

from gemseo_process_builder.workers.gemseo_loader import require_gemseo
from gemseo_process_builder.workers.server import RequestContext

FIRST_NAME = re.compile(r"\s*([A-Za-z_]\w*)")


def _node_of(line: str, mapping: dict[str, Any]) -> str:
    """The node of the Python variable a line starts with, else the target."""
    match = FIRST_NAME.match(line)
    variables: dict[str, str] = mapping.get("variables", {})
    if match and match.group(1) in variables:
        return variables[match.group(1)]
    return str(mapping.get("target", ""))


def dry_run(source: str, mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """Build what a script runs, without running it.

    Args:
        source: The generated script.
        mapping: Its sidecar mapping (``kind``, ``target``, ``variables``).

    Returns:
        The problems, as ``{"node", "message", "line"}``; empty if none.
    """
    module_name = f"gpb_dry_run_{uuid.uuid4().hex}"
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f"{module_name}.py"
        path.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:  # pragma: no cover - a .py file
            return [
                {
                    "node": mapping.get("target", ""),
                    "message": "Cannot load the script.",
                    "line": 0,
                }
            ]
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            if mapping.get("kind") == "scenario":
                module.build_scenario()
            else:
                module.build_process()
        except Exception as error:  # Any error of user code or GEMSEO.
            frames = [
                frame
                for frame in traceback.extract_tb(error.__traceback__)
                if Path(frame.filename) == path
            ]
            line = (frames[-1].line or "") if frames else ""
            return [
                {
                    "node": _node_of(line, mapping),
                    "message": f"{type(error).__name__}: {error}",
                    "line": frames[-1].lineno if frames else 0,
                }
            ]
        finally:
            sys.modules.pop(module_name, None)
    return []


def _dry_run(params: dict[str, Any], context: RequestContext) -> list[dict[str, Any]]:
    require_gemseo()
    return dry_run(str(params.get("source", "")), dict(params.get("mapping") or {}))


def register(server: Any) -> None:
    """Add the code generation methods to the worker."""
    server.add("codegen.dry_run", _dry_run)
