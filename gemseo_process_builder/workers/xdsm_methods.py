"""XDSM diagrams of the scenarios (runs in the worker; SPEC § 8.5).

GEMSEO draws the XDSM of a scenario (``scenario.xdsmize``) as the JSON read by
XDSMjs: one diagram for the process (``root``) and one per sub-scenario. The
page draws it with its own renderer; the PDF goes through pyXDSM and LaTeX.
"""

import importlib.util
import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

from gemseo_process_builder.workers.gemseo_loader import require_gemseo
from gemseo_process_builder.workers.server import RequestContext
from gemseo_process_builder.workers.server import WorkerError

PDF_COMPILER = "pdflatex"


def _scenario(source: str, folder: Path) -> Any:
    """Import a generated script and build its scenario."""
    module_name = f"gpb_xdsm_{uuid.uuid4().hex}"
    path = folder / f"{module_name}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - a .py file
        raise WorkerError("xdsm_error", "Cannot load the script.")
    module: ModuleType = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        if not hasattr(module, "build_scenario"):
            raise WorkerError(
                "xdsm_error",
                "The XDSM shows the process of an optimization, a DOE or a "
                "parametric study: select one of these drivers.",
            )
        return module.build_scenario()
    except WorkerError:
        raise
    except Exception as error:  # Any error of user code or GEMSEO.
        message = f"The scenario cannot be built: {type(error).__name__}: {error}"
        raise WorkerError("xdsm_error", message) from None
    finally:
        sys.modules.pop(module_name, None)


def build(source: str) -> dict[str, Any]:
    """The XDSM diagrams of the scenario of a generated script."""
    require_gemseo()
    with tempfile.TemporaryDirectory() as folder:
        scenario = _scenario(source, Path(folder))
        xdsm = scenario.xdsmize(save_html=False, show_html=False, directory_path=folder)
    schema = xdsm.json_schema
    diagrams: dict[str, Any] = (
        json.loads(schema) if isinstance(schema, str) else dict(schema)
    )
    return diagrams


def capabilities() -> dict[str, Any]:
    """Whether the PDF export is possible, and why not."""
    if importlib.util.find_spec("pyxdsm") is None:
        reason = "The PDF export needs pyXDSM: pip install pyxdsm."
        return {"pdf": False, "reason": reason}
    if shutil.which(PDF_COMPILER) is None:
        reason = "The PDF export needs LaTeX (pdflatex) on the PATH."
        return {"pdf": False, "reason": reason}
    return {"pdf": True, "reason": ""}


def pdf(source: str, path: Path) -> str:
    """Write the XDSM of the scenario of a generated script as a PDF file."""
    available = capabilities()
    if not available["pdf"]:
        raise WorkerError("xdsm_error", available["reason"])
    require_gemseo()
    with tempfile.TemporaryDirectory() as folder:
        scenario = _scenario(source, Path(folder))
        scenario.xdsmize(
            save_html=False,
            show_html=False,
            save_pdf=True,
            pdf_build=True,
            directory_path=folder,
            file_name="xdsm",
        )
        built = Path(folder) / "xdsm.pdf"
        if not built.is_file():
            raise WorkerError("xdsm_error", "LaTeX did not produce the PDF file.")
        shutil.copyfile(built, path)
    return str(path)


def _build(params: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    return build(str(params.get("source", "")))


def _capabilities(params: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    return capabilities()


def _pdf(params: dict[str, Any], context: RequestContext) -> str:
    return pdf(str(params.get("source", "")), Path(str(params.get("path", ""))))


def register(server: Any) -> None:
    """Add the XDSM methods to the worker."""
    server.add("xdsm.build", _build)
    server.add("xdsm.capabilities", _capabilities)
    server.add("xdsm.pdf", _pdf)
