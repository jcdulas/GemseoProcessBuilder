"""User preferences, stored as JSON in the user's configuration folder."""

import json
import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError
from PySide6.QtCore import QStandardPaths

from gemseo_process_builder.core.atomic_write import write_text_atomically

_LOGGER = logging.getLogger(__name__)

PREFERENCES_SCHEMA_VERSION = 1
MAX_RECENT_PROJECTS = 10


class Preferences(BaseModel):
    """Everything the user can configure outside a project."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    schema_version: int = PREFERENCES_SCHEMA_VERSION
    catalog_paths: list[str] = []
    """Folders scanned for reusable components, for every project."""

    python_interpreter: str = ""
    """Interpreter of the worker and runner; empty means the application's own."""

    code_editor: str = ""
    """Command opening Python files, ``{file}`` standing for the path; empty
    means Visual Studio Code when installed, else the text editor of the system."""

    max_undo: int = Field(default=500, ge=1, le=10_000)
    layout: dict[str, Any] = {}
    """Panel sizes and collapsed states, owned by the page."""

    recent_projects: list[str] = []
    log_level: str = "INFO"
    stop_timeout_s: float = Field(default=10.0, gt=0)
    allow_concurrent_runs: bool = False
    show_unused_outputs: bool = True
    """Whether unused outputs are reported as info by the validation."""


def default_preferences_path() -> Path:
    """Return the preferences file in the user's configuration folder."""
    folder = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    )
    return Path(folder) / "preferences.json"


class PreferencesStore:
    """Load, change and save the preferences file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.preferences = self._load()
        self._listeners: list[Callable[[Preferences, Preferences], None]] = []

    def on_change(self, listener: Callable[[Preferences, Preferences], None]) -> None:
        """Call ``listener(old, new)`` after each change of the preferences."""
        self._listeners.append(listener)

    def _load(self) -> Preferences:
        if not self.path.exists():
            return Preferences()
        try:
            return Preferences.model_validate(
                json.loads(self.path.read_text(encoding="utf-8"))
            )
        except (ValueError, ValidationError) as error:
            backup = self.path.with_suffix(".json.bak")
            shutil.copyfile(self.path, backup)
            _LOGGER.warning(
                "The preferences file is invalid and was reset to defaults "
                "(the old file is kept as %s): %s",
                backup,
                error,
            )
            return Preferences()

    def save(self) -> None:
        """Write the preferences to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomically(self.path, self.preferences.model_dump_json(indent=2))

    def update(self, values: dict[str, Any]) -> Preferences:
        """Change some preferences, validate them and save.

        Args:
            values: The preferences to change, by name.

        Returns:
            The updated preferences.

        Raises:
            ValidationError: When a value is invalid; nothing is changed then.
        """
        old = self.preferences
        self.preferences = Preferences.model_validate(old.model_dump() | values)
        self.save()
        for listener in self._listeners:
            listener(old, self.preferences)
        return self.preferences

    def add_recent_project(self, path: str) -> None:
        """Put a project at the top of the recent projects and save."""
        recent = [path] + [p for p in self.preferences.recent_projects if p != path]
        self.update({"recent_projects": recent[:MAX_RECENT_PROJECTS]})
