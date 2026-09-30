"""Export of the project as a Python script: ``codegen.*`` methods."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from PySide6.QtWidgets import QFileDialog
from PySide6.QtWidgets import QWidget

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.codegen.generator import CodegenError
from gemseo_process_builder.codegen.generator import GeneratedScript
from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.codegen.generator import script_file_name
from gemseo_process_builder.codegen.generator import write_script

_LOGGER = logging.getLogger(__name__)

AskScriptPath = Callable[[Path], Path | None]
"""Ask where to write a script, suggesting a path; ``None`` if cancelled."""


def qt_ask_script_path(parent: QWidget | None) -> AskScriptPath:
    """A native "save file" dialog for Python scripts."""

    def ask(suggested: Path) -> Path | None:
        path, _ = QFileDialog.getSaveFileName(
            parent, "Export Python script", str(suggested), "Python scripts (*.py)"
        )
        if not path:
            return None
        return Path(path if path.endswith(".py") else path + ".py")

    return ask


class ExportParams(BaseModel):
    """Parameters of ``codegen.export`` and ``codegen.preview``."""

    target: str | None = None
    """The node to run; the root model by default."""

    path: str | None = None
    """Where to write the script; asked to the user when missing."""


class CodegenController:
    """Generate scripts from the current project."""

    def __init__(
        self, session: ProjectSession, bridge: Bridge, ask_path: AskScriptPath
    ) -> None:
        self.session = session
        self.bridge = bridge
        self.ask_path = ask_path

    def _generate(self, target: str) -> GeneratedScript:
        project_file = self.session.path.name if self.session.path else ""
        try:
            return generate(self.session.project, target, project_file)
        except CodegenError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from error

    def preview(self, params: ExportParams) -> dict[str, Any]:
        """The script without writing it (``codegen.preview``)."""
        script = self._generate(params.target or self.session.project.root.id)
        return {"source": script.source, "mapping": script.mapping}

    def export(self, params: ExportParams) -> dict[str, Any]:
        """Write the script and its mapping sidecar (``codegen.export``)."""
        project = self.session.project
        target = params.target or project.root.id
        script = self._generate(target)
        if params.path:
            path = Path(params.path)
        else:
            folder = self.session.path.parent if self.session.path else Path.home()
            chosen = self.ask_path(folder / script_file_name(project, target))
            if chosen is None:
                return {"exported": False}
            path = chosen
        write_script(script, path)
        _LOGGER.info("Exported %s", path)
        return {"exported": True, "path": str(path)}

    def register(self) -> None:
        """Register the ``codegen.*`` methods."""
        self.bridge.registry.add("codegen.preview", self.preview)
        self.bridge.registry.add("codegen.export", self.export)
