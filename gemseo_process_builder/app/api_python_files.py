"""Python files of discipline classes, created and edited from the inspector.

``pythonFile.*`` methods: create a module with a discipline class for a
component, read and rewrite its variables, open it in the user's editor. The
files are only read and written here (``core/discipline_file.py``); they are
imported by the worker, which the component service asks again when a file
changes on disk.
"""

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from typing import Literal

from pydantic import BaseModel
from PySide6.QtCore import QFileSystemWatcher
from PySide6.QtCore import QObject
from PySide6.QtCore import QTimer

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.component_service import ComponentService
from gemseo_process_builder.app.preferences import PreferencesStore
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.core.atomic_write import write_text_atomically
from gemseo_process_builder.core.commands import CommandError
from gemseo_process_builder.core.commands import SetNodeProperties
from gemseo_process_builder.core.discipline_file import DisciplineFileError
from gemseo_process_builder.core.discipline_file import FileVariable
from gemseo_process_builder.core.discipline_file import new_module
from gemseo_process_builder.core.discipline_file import read_variables
from gemseo_process_builder.core.discipline_file import write_variables
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import iter_nodes

WATCH_DELAY_MS = 300
VSCODE_COMMANDS = ("code", "vscode", "code-insiders")
"""The names of Visual Studio Code on the path, depending on the machine."""


def vscode() -> str | None:
    """Visual Studio Code: on the path, or where Windows installs it."""
    for name in VSCODE_COMMANDS:
        found = shutil.which(name)
        if found:
            return found
    if sys.platform == "win32":
        folders = [
            os.environ.get("LOCALAPPDATA", ""),
            os.environ.get("PROGRAMFILES", ""),
        ]
        for folder in filter(None, folders):
            for program in ("Programs/Microsoft VS Code", "Microsoft VS Code"):
                path = Path(folder) / program / "Code.exe"
                if path.is_file():
                    return str(path)
    return None


FILE_KINDS = ("python_class", "python_function")


class VariableModel(BaseModel):
    """A variable of the table of the inspector."""

    name: str
    direction: Literal["in", "out"]
    default: list[float] | None = None


class CreateParams(BaseModel):
    """Parameters of ``pythonFile.create``."""

    id: str
    path: str
    class_name: str
    description: str = ""
    variables: list[VariableModel]


class NodeParams(BaseModel):
    """Parameters naming a component."""

    id: str


class VariablesParams(BaseModel):
    """Parameters of ``pythonFile.setVariables``."""

    id: str
    variables: list[VariableModel]


def editor_command(configured: str, path: Path) -> list[str]:
    """The command opening a file in the user's editor.

    The configured command (``{file}`` is replaced by the path, else the path is
    added at the end); otherwise Visual Studio Code when installed (``code``,
    ``vscode`` or its install folder, depending on the machine), else the
    text editor of the system. Never the program associated with ``.py``
    files, which could run them.
    """
    if configured.strip():
        # Windows paths keep their backslashes; their quotes are removed.
        parts = [
            part.strip('"')
            for part in shlex.split(configured, posix=sys.platform != "win32")
        ]
        if any("{file}" in part for part in parts):
            return [part.replace("{file}", str(path)) for part in parts]
        return [*parts, str(path)]
    code = vscode()
    if code:
        return [code, str(path)]
    if sys.platform == "win32":
        return ["notepad.exe", str(path)]
    if sys.platform == "darwin":
        return ["open", "-t", str(path)]
    return ["xdg-open", str(path)]


class PythonFileService(QObject):
    """Create and edit the files of discipline classes; follow their changes."""

    def __init__(
        self,
        session: ProjectSession,
        bridge: Bridge,
        components: ComponentService,
        preferences: PreferencesStore,
    ) -> None:
        super().__init__()
        self.session = session
        self.bridge = bridge
        self.components = components
        self.preferences = preferences
        self._watcher = QFileSystemWatcher(self)
        self._changed: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(WATCH_DELAY_MS)
        self._timer.timeout.connect(self._reload)
        self._watcher.fileChanged.connect(self._file_changed)
        session.on_change(self.watch)

    # Files ---------------------------------------------------------------------

    def _component(self, node_id: str) -> ComponentNode:
        node = self.session.project.find(node_id)
        if not isinstance(node, ComponentNode):
            raise BridgeError(ErrorCode.NOT_FOUND, f"No component {node_id}.")
        return node

    def _file(self, node: ComponentNode) -> Path:
        path = str(node.config.get("module_path") or "")
        if not path:
            msg = f"{node.name} has no Python file: create one, or choose one."
            raise BridgeError(ErrorCode.INVALID_PARAMS, msg)
        return Path(path)

    def create(self, params: CreateParams) -> dict[str, Any]:
        """Write a new module with a discipline class, used by the component."""
        node = self._component(params.id)
        path = Path(params.path)
        if path.suffix != ".py":
            path = path.with_suffix(".py")
        if path.exists():
            msg = f"{path.name} already exists: choose a new name, it is not replaced."
            raise BridgeError(ErrorCode.CONFLICT, msg)
        try:
            source = new_module(
                params.class_name,
                params.description,
                [FileVariable(**v.model_dump()) for v in params.variables],
            )
        except DisciplineFileError as error:
            raise BridgeError(ErrorCode.INVALID_PARAMS, str(error)) from None
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomically(path, source)
        # The file replaces an installed module the component may have used.
        config = {key: value for key, value in node.config.items() if key != "module"}
        config.update(module_path=str(path), init_args={})
        config["class"] = params.class_name
        try:
            self.session.document.execute(
                SetNodeProperties(
                    id=node.id,
                    values={"config": config},
                    label_text="Create a Python file",
                )
            )
        except CommandError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        self.watch()
        return {"path": str(path)}

    def variables(self, params: NodeParams) -> dict[str, Any]:
        """The variables of the class, when the application writes them."""
        node = self._component(params.id)
        path = self._file(node)
        class_name = str(node.config.get("class") or "")
        try:
            found = read_variables(path.read_text(encoding="utf-8"), class_name)
        except OSError as error:
            return {
                "path": str(path),
                "managed": False,
                "variables": [],
                "error": str(error),
            }
        except DisciplineFileError as error:
            return {
                "path": str(path),
                "managed": False,
                "variables": [],
                "error": str(error),
            }
        return {
            "path": str(path),
            "managed": found is not None,
            "variables": [vars(variable) for variable in found or []],
            "error": "",
        }

    def set_variables(self, params: VariablesParams) -> dict[str, Any]:
        """Rewrite the variables of the class, then read its ports again."""
        node = self._component(params.id)
        path = self._file(node)
        class_name = str(node.config.get("class") or "")
        try:
            source = write_variables(
                path.read_text(encoding="utf-8"),
                class_name,
                [FileVariable(**v.model_dump()) for v in params.variables],
            )
        except OSError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        except DisciplineFileError as error:
            raise BridgeError(ErrorCode.INVALID_PARAMS, str(error)) from None
        write_text_atomically(path, source)
        self.components.introspect(node.id)
        return self.variables(NodeParams(id=node.id))

    def open(self, params: NodeParams) -> None:
        """Open the file of a component in the user's editor."""
        path = self._file(self._component(params.id))
        if not path.exists():
            raise BridgeError(ErrorCode.NOT_FOUND, f"{path} does not exist.")
        command = editor_command(self.preferences.preferences.code_editor, path)
        try:
            subprocess.Popen(command, close_fds=True)
        except OSError as error:
            msg = (
                f"The editor could not be started ({command[0]}: {error}). "
                "Choose it in Tools > Preferences > Code editor."
            )
            raise BridgeError(ErrorCode.CONFLICT, msg) from None

    # Watching ------------------------------------------------------------------

    def _paths(self) -> dict[str, list[str]]:
        """The Python files of the components, and the components using each."""
        paths: dict[str, list[str]] = {}
        for node, _ in iter_nodes(self.session.project.root):
            if isinstance(node, ComponentNode) and node.kind in FILE_KINDS:
                path = str(node.config.get("module_path") or "")
                if path and os.path.exists(path):
                    paths.setdefault(
                        os.path.normcase(os.path.abspath(path)), []
                    ).append(node.id)
        return paths

    def watch(self) -> None:
        """Follow the files of the components (some editors replace the file)."""
        wanted = set(self._paths())
        watched = {os.path.normcase(os.path.abspath(p)) for p in self._watcher.files()}
        missing = [path for path in wanted if path not in watched]
        if missing:
            self._watcher.addPaths(missing)

    def _file_changed(self, path: str) -> None:
        self._changed.add(os.path.normcase(os.path.abspath(path)))
        self._timer.start()

    def _reload(self) -> None:
        """Read the ports of the components whose file changed."""
        paths = self._paths()
        for path in self._changed:
            nodes = paths.get(path, [])
            for node_id in nodes:
                self.components.introspect(node_id)
            self.bridge.emit_event("pythonFile.changed", {"path": path, "nodes": nodes})
        self._changed.clear()
        self.watch()

    def register(self) -> None:
        """Register the ``pythonFile.*`` methods."""
        registry = self.bridge.registry
        registry.add("pythonFile.create", self.create)
        registry.add("pythonFile.variables", self.variables)
        registry.add("pythonFile.setVariables", self.set_variables)
        registry.add("pythonFile.open", self.open)
