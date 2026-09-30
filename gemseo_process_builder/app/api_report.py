"""The project report: ``report.*`` methods (SPEC § 13).

The page draws the diagrams and chooses the content; the report is built here
from the project data and written as HTML, or printed to PDF.
"""

import tempfile
from pathlib import Path
from typing import Any
from typing import Literal

from pydantic import BaseModel

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.core.atomic_write import write_text_atomically
from gemseo_process_builder.report.builder import IMAGE_TYPES
from gemseo_process_builder.report.builder import Diagram
from gemseo_process_builder.report.builder import ReportOptions
from gemseo_process_builder.report.builder import build_report
from gemseo_process_builder.report.pdf import PdfError
from gemseo_process_builder.report.pdf import PdfPrinter
from gemseo_process_builder.results.store import RunStore


class ExportParams(BaseModel):
    """Parameters of ``report.export``."""

    path: str
    format: Literal["html", "pdf"]
    options: ReportOptions
    diagrams: list[Diagram] = []


class ReportController:
    """Build and write project reports."""

    def __init__(self, session: ProjectSession, runs: RunStore, bridge: Bridge) -> None:
        self.session = session
        self.runs = runs
        self.bridge = bridge
        self.printer = PdfPrinter()

    def sources(self) -> list[dict[str, Any]]:
        """The runs a report can show, with their post-processing outputs."""
        entries = []
        for entry in self.runs.entries():
            if entry["missing"]:
                continue
            folder = Path(entry["folder"]) / "postproc"
            outputs = (
                sorted(
                    path.name
                    for path in folder.iterdir()
                    if path.is_dir()
                    and any(file.suffix in IMAGE_TYPES for file in path.iterdir())
                )
                if folder.is_dir()
                else []
            )
            entries.append(
                {
                    "id": entry["id"],
                    "name": entry.get("name") or entry["id"],
                    "driver": entry.get("driver_path") or entry.get("driver_name", ""),
                    "status": entry.get("status", ""),
                    "postprocessings": outputs,
                }
            )
        return entries

    def export(self, params: ExportParams) -> str:
        """Write the report; return the path of the file (in a background thread)."""
        html = build_report(
            self.session.project, params.options, params.diagrams, self.runs.folder_of
        )
        path = Path(params.path).with_suffix(f".{params.format}")
        try:
            if params.format == "html":
                write_text_atomically(path, html)
                return str(path)
            with tempfile.TemporaryDirectory() as folder:
                page = Path(folder) / "report.html"
                page.write_text(html, encoding="utf-8")
                self.printer.print(page, path)
        except PdfError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        except OSError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        return str(path)

    def register(self) -> None:
        """Register the ``report.*`` methods."""
        registry = self.bridge.registry
        registry.add("report.sources", self.sources)
        registry.add("report.export", self.export, background=True)
