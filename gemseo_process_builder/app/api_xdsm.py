"""The XDSM of a driver for the page: ``xdsm.*`` methods (SPEC § 8.5).

The script of the driver is generated here, then the worker builds its
scenario and asks GEMSEO for the XDSM: GEMSEO never runs in the UI process.
"""

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.app.worker_client import WorkerClient
from gemseo_process_builder.app.worker_client import WorkerRequestError
from gemseo_process_builder.app.worker_client import WorkerUnavailableError
from gemseo_process_builder.app.xdsm_export import standalone_html
from gemseo_process_builder.codegen.generator import CodegenError
from gemseo_process_builder.codegen.generator import GeneratedScript
from gemseo_process_builder.codegen.generator import generate

TIMEOUT_S = 60.0
PDF_TIMEOUT_S = 120.0


class TargetParams(BaseModel):
    """Parameters naming the driver of an XDSM."""

    target: str


class ExportParams(BaseModel):
    """Parameters of ``xdsm.exportHtml`` and ``xdsm.exportPdf``."""

    target: str
    path: str


class XdsmController:
    """Build and export the XDSM of drivers."""

    def __init__(
        self, session: ProjectSession, bridge: Bridge, worker: WorkerClient
    ) -> None:
        self.session = session
        self.bridge = bridge
        self.worker = worker

    def _script(self, target: str) -> GeneratedScript:
        try:
            return generate(self.session.project, target)
        except CodegenError as error:
            raise BridgeError(ErrorCode.INVALID_PARAMS, str(error)) from None

    def _call(self, method: str, params: dict[str, Any], timeout: float) -> Any:
        try:
            return self.worker.call(method, params, timeout=timeout)
        except WorkerRequestError as error:
            raise BridgeError(error.code, error.message) from None
        except WorkerUnavailableError as error:
            raise BridgeError(ErrorCode.WORKER_UNAVAILABLE, str(error)) from None

    def build(self, params: TargetParams) -> dict[str, Any]:
        """The XDSM diagrams of a driver, with the nodes of their boxes.

        Returns:
            ``diagrams`` (GEMSEO's XDSM JSON) and ``nodes``: the node id of the
            driver (``target``), of each discipline and of each nested scenario,
            by name.
        """
        script = self._script(params.target)
        diagrams = self._call("xdsm.build", {"source": script.source}, TIMEOUT_S)
        mapping = script.mapping
        return {
            "diagrams": diagrams,
            "nodes": {
                "target": params.target,
                "disciplines": {
                    name: node_id
                    for node_id, name in mapping.get("disciplines", {}).items()
                },
                "scenarios": {
                    name: node_id
                    for node_id, name in mapping.get("scenarios", {}).items()
                },
            },
        }

    def capabilities(self) -> Any:
        """Whether the PDF export is possible (pyXDSM and LaTeX), and why not."""
        return self._call("xdsm.capabilities", {}, TIMEOUT_S)

    def export_html(self, params: ExportParams) -> str:
        """Write a standalone HTML page showing the XDSM of a driver."""
        if not params.path:
            raise BridgeError(ErrorCode.INVALID_PARAMS, "Choose the HTML file first.")
        diagrams = self.build(TargetParams(target=params.target))["diagrams"]
        node = self.session.project.find(params.target)
        title = f"{self.session.project.metadata.name}: {node.name if node else ''}"
        path = Path(params.path)
        path.write_text(standalone_html(diagrams, title), encoding="utf-8")
        return str(path)

    def export_pdf(self, params: ExportParams) -> Any:
        """Write the XDSM of a driver as a PDF file (pyXDSM and LaTeX)."""
        if not params.path:
            raise BridgeError(ErrorCode.INVALID_PARAMS, "Choose the PDF file first.")
        script = self._script(params.target)
        return self._call(
            "xdsm.pdf", {"source": script.source, "path": params.path}, PDF_TIMEOUT_S
        )

    def register(self) -> None:
        """Register the ``xdsm.*`` methods."""
        registry = self.bridge.registry
        registry.add("xdsm.build", self.build, background=True)
        registry.add("xdsm.capabilities", self.capabilities, background=True)
        registry.add("xdsm.exportHtml", self.export_html, background=True)
        registry.add("xdsm.exportPdf", self.export_pdf, background=True)
