"""The demos of the Library: ``demos.list`` and ``demos.open`` (SPEC § 7.6).

Opening a demo copies it to a folder of the user, then opens the copy like any
GEMSEO script (see ``core/demos.py``).
"""

from collections.abc import Sequence
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
        self,
        projects: ProjectController,
        copies: Path,
        folder: Path | None = None,
        worker: Any = None,
    ) -> None:
        self.projects = projects
        self.copies = copies
        self.folder = folder if folder is not None else demos_folder()
        self.worker = worker
        """Tells the packages missing from the Python of the runs, if given."""

    def list(self) -> list[dict[str, Any]]:
        """The demos, with their titles and summaries (``demos.list``)."""
        if self.folder is None:
            return []
        demos = find_demos(self.folder)
        missing = self._missing(sorted({n for demo in demos for n in demo.requires}))
        return [
            {
                "id": demo.id,
                "title": demo.title,
                "summary": demo.summary,
                "requires": list(demo.requires),
                "missing": [name for name in demo.requires if name in missing],
            }
            for demo in demos
        ]

    def _missing(self, names: Sequence[str]) -> set[str]:
        """The packages missing from the Python of the runs (none when unknown)."""
        if not names or self.worker is None:
            return set()
        try:
            return set(
                self.worker.call("catalog.missing", {"names": names}, timeout=10.0)
            )
        except Exception:  # The worker is not ready: no note rather than no list.
            return set()

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
        # In the background: the worker tells the packages missing.
        registry.add("demos.list", self.list, background=True)
        registry.add("demos.open", self.open)
