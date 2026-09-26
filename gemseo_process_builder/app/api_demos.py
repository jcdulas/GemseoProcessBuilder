"""The demos of the Library: ``demos.list`` and ``demos.open`` (SPEC § 7.6).

Opening a demo copies it to a folder of the user, then opens the copy like any
GEMSEO script (see ``core/demos.py``).
"""

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from gemseo_process_builder.app.api_project import ProjectController
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.core.demos import copy_demo
from gemseo_process_builder.core.demos import demos_folder
from gemseo_process_builder.core.demos import find_demos


class DemoParams(BaseModel):
    """Parameters of ``demos.open``."""

    id: str


class DemoService:
    """List the demos, and open copies of them.

    Args:
        projects: The controller opening projects.
        copies: The folder of the user receiving the copies of the demos.
        folder: The demos; by default, those of the package.
    """

    def __init__(
        self, projects: ProjectController, copies: Path, folder: Path | None = None
    ) -> None:
        self.projects = projects
        self.copies = copies
        self.folder = folder if folder is not None else demos_folder()

    def list(self) -> list[dict[str, Any]]:
        """The demos, with their titles and summaries (``demos.list``)."""
        if self.folder is None:
            return []
        return [
            {"id": demo.id, "title": demo.title, "summary": demo.summary}
            for demo in find_demos(self.folder)
        ]

    def open(self, params: DemoParams) -> dict[str, Any]:
        """Copy a demo to the folder of the user and open it (``demos.open``)."""
        demos = (
            {demo.id: demo for demo in find_demos(self.folder)} if self.folder else {}
        )
        demo = demos.get(params.id)
        if demo is None or self.folder is None:
            msg = f"There is no demo {params.id}."
            raise BridgeError(ErrorCode.NOT_FOUND, msg)
        if not self.projects.confirm_discard():
            return {"cancelled": True}
        try:
            script = copy_demo(self.folder, demo, self.copies)
        except OSError as error:
            msg = f"The demo cannot be copied to {self.copies}: {error}"
            raise BridgeError(ErrorCode.INVALID_PARAMS, msg) from None
        return {**self.projects.open_path(script), "path": str(script)}

    def register(self) -> None:
        """Register the ``demos.*`` methods."""
        registry = self.projects.bridge.registry
        registry.add("demos.list", self.list)
        registry.add("demos.open", self.open)
