"""Continuous validation and quick fixes: ``validation.*`` methods.

The project is validated 300 ms after the last change; the problems are pushed
to the page with a ``validation.updated`` event.
"""

import logging
from typing import Any

from pydantic import BaseModel
from PySide6.QtCore import QObject
from PySide6.QtCore import QTimer

from gemseo_process_builder.app.api_resolve import ResolutionService
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.component_service import ComponentService
from gemseo_process_builder.app.preferences import PreferencesStore
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.core.commands import CommandError
from gemseo_process_builder.core.quick_fixes import FIX_LABELS
from gemseo_process_builder.core.quick_fixes import fix_command
from gemseo_process_builder.core.validation import Problem
from gemseo_process_builder.core.validation import ValidationContext
from gemseo_process_builder.core.validation import validate

_LOGGER = logging.getLogger(__name__)

DEBOUNCE_MS = 300


class QuickFixParams(BaseModel):
    """Parameters of ``validation.quickFix``."""

    key: str
    fix: str


class ValidationService(QObject):
    """Validate the project after changes and apply quick fixes."""

    def __init__(
        self,
        session: ProjectSession,
        bridge: Bridge,
        resolution: ResolutionService,
        components: ComponentService,
        preferences: PreferencesStore,
    ) -> None:
        super().__init__()
        self.session = session
        self.bridge = bridge
        self.resolution = resolution
        self.components = components
        self.preferences = preferences
        self.problems: list[Problem] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.run)
        session.document.on_change(lambda changes, rev: self._timer.start())
        session.on_change(self._timer.start)
        components.status_changed.connect(self._timer.start)
        preferences.on_change(lambda old, new: self._timer.start())

    def run(self) -> list[Problem]:
        """Validate now and publish the problems."""
        errors = {
            node_id: state["error"]
            for node_id, state in self.components.states.items()
            if state["state"] == "error"
        }
        context = ValidationContext(
            self.session.project,
            self.resolution.current(),
            errors,
            {"show_unused_outputs": self.preferences.preferences.show_unused_outputs},
        )
        self.problems = validate(context)
        self.bridge.emit_event("validation.updated", self.state())
        return self.problems

    def state(self) -> dict[str, Any]:
        """The problems and the labels of their fixes."""
        return {
            "problems": [problem.to_dict() for problem in self.problems],
            "fix_labels": FIX_LABELS,
        }

    def quick_fix(self, params: QuickFixParams) -> dict[str, Any]:
        """Apply a fix to a problem (``validation.quickFix``)."""
        problem = next((p for p in self.problems if p.key == params.key), None)
        if problem is None:
            raise BridgeError(ErrorCode.NOT_FOUND, "This problem is already fixed.")
        try:
            command = fix_command(problem, params.fix)
        except ValueError as error:
            raise BridgeError(ErrorCode.INVALID_PARAMS, str(error)) from None
        if command is None:  # Not a command: introspect again.
            self.components.introspect(problem.node)
            return {"rev": self.session.document.rev}
        try:
            rev = self.session.document.execute(command)
        except CommandError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        return {"rev": rev}

    def register(self) -> None:
        """Register the ``validation.*`` methods."""
        registry = self.bridge.registry
        registry.add("validation.run", lambda: (self.run(), self.state())[1])
        registry.add("validation.state", self.state)
        registry.add("validation.quickFix", self.quick_fix)
