"""The executable wrapper editor: ``executable.*`` methods (SPEC § 7.5).

Descriptors and rules only need Pydantic: they are read, written and previewed
in the UI process. Test runs execute the wrapper in the worker.
"""

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic import TypeAdapter
from pydantic import ValidationError
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.app.worker_client import WorkerClient
from gemseo_process_builder.app.worker_client import WorkerRequestError
from gemseo_process_builder.app.worker_client import WorkerUnavailableError
from gemseo_process_builder.core.commands import AddNode
from gemseo_process_builder.core.commands import Command
from gemseo_process_builder.core.commands import CommandError
from gemseo_process_builder.core.commands import SetNodeProperties
from gemseo_process_builder.core.commands import SetPorts
from gemseo_process_builder.core.ids import new_id
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.ports import merge_ports
from gemseo_process_builder.runtime.parsing import read_output
from gemseo_process_builder.runtime.spec import DESCRIPTOR_SUFFIX
from gemseo_process_builder.runtime.spec import ExecutableSpec
from gemseo_process_builder.runtime.spec import OutputRule
from gemseo_process_builder.runtime.spec import load_descriptor
from gemseo_process_builder.runtime.spec import save_descriptor
from gemseo_process_builder.runtime.spec import spec_data
from gemseo_process_builder.runtime.spec import spec_ports

MAX_SAMPLE_BYTES = 5 * 1024 * 1024
"""Samples beyond this size are cut (the editor shows a warning)."""

TEST_RUN_TIMEOUT_S = 600.0
RULE: TypeAdapter[OutputRule] = TypeAdapter(OutputRule)


class PathParams(BaseModel):
    """Parameters naming a file."""

    path: str


class SaveParams(BaseModel):
    """Parameters of ``executable.saveDescriptor``."""

    path: str
    spec: dict[str, Any]
    base_folder: str = ""


class PreviewParams(BaseModel):
    """Parameters of ``executable.preview``."""

    rule: dict[str, Any]
    text: str


class ApplyParams(BaseModel):
    """Parameters of ``executable.apply``: a wrapper for a component.

    Either ``descriptor_path`` names a descriptor, or ``spec`` holds the
    wrapper itself, its relative paths referring to ``base_folder``.
    """

    id: str
    descriptor_path: str = ""
    spec: dict[str, Any] = {}
    base_folder: str = ""


class AddParams(BaseModel):
    """Parameters of ``executable.add``: a new component running a wrapper."""

    parent: str
    descriptor_path: str = ""
    spec: dict[str, Any] = {}
    base_folder: str = ""


class TestRunParams(BaseModel):
    """Parameters of ``executable.testRun``."""

    spec: dict[str, Any]
    inputs: dict[str, Any] = {}
    base_folder: str = ""


def _spec(data: dict[str, Any]) -> ExecutableSpec:
    try:
        return ExecutableSpec.model_validate(data)
    except ValidationError as error:
        raise BridgeError(
            ErrorCode.INVALID_PARAMS, f"Invalid wrapper: {error}"
        ) from None


def editable_spec(path: Path) -> dict[str, Any]:
    """A descriptor as the editor holds it: templates inline, files absolute."""
    try:
        spec, folder = load_descriptor(path)
    except ValueError as error:
        raise BridgeError(ErrorCode.INVALID_PARAMS, str(error)) from None
    templates = []
    for template in spec.templates:
        content = template.content
        if content is None:
            content = (folder / template.template).read_text(encoding="utf-8")
        templates.append(
            template.model_copy(update={"template": "", "content": content})
        )
    files = [str((folder / name).resolve()) for name in spec.files]
    edited = spec.model_copy(update={"templates": templates, "files": files})
    return {"spec": spec_data(edited), "base_folder": str(folder)}


def write_descriptor(path: Path, spec: ExecutableSpec, base_folder: str) -> Path:
    """Write a descriptor and its templates, with paths relative to it.

    Inline templates become files next to the descriptor, named after the
    files they write (``input.txt.tmpl``).
    """
    if not path.name.endswith(DESCRIPTOR_SUFFIX):
        path = path.with_name(path.name.split(".")[0] + DESCRIPTOR_SUFFIX)
    folder = path.parent
    base = Path(base_folder) if base_folder else folder
    templates = []
    for template in spec.templates:
        if template.content is not None:
            name = f"{template.target}.tmpl"
            (folder / name).write_text(template.content, encoding="utf-8", newline="\n")
            templates.append(
                template.model_copy(update={"template": name, "content": None})
            )
        else:
            source = (base / template.template).resolve()
            templates.append(
                template.model_copy(update={"template": _relative(source, folder)})
            )
    files = [_relative((base / name).resolve(), folder) for name in spec.files]
    save_descriptor(
        spec.model_copy(update={"templates": templates, "files": files}), path
    )
    return path


def _relative(path: Path, folder: Path) -> str:
    """A path relative to a folder when possible (same drive), else absolute."""
    try:
        return Path(os.path.relpath(path, folder)).as_posix()
    except ValueError:
        return path.as_posix()


def preview(rule_data: dict[str, Any], text: str) -> dict[str, Any]:
    """The value a rule reads in a sample, or why it cannot."""
    try:
        rule = RULE.validate_python(rule_data)
    except ValidationError as error:
        return {"value": None, "error": f"Incomplete rule: {error.errors()[0]['msg']}."}
    if rule.kind == "file":
        return {"value": rule.file, "error": ""}
    try:
        return {"value": read_output(rule, text, Path()), "error": ""}
    except ValueError as error:
        return {"value": None, "error": str(error)}


class ExecutableController:
    """Methods of the wrapper editor."""

    def __init__(
        self, session: ProjectSession, bridge: Bridge, worker: WorkerClient
    ) -> None:
        self.session = session
        self.bridge = bridge
        self.worker = worker

    def add(self, params: AddParams) -> str:
        """Add a component running a wrapper, with its ports; return its id."""
        config, spec = self._config(params, {})
        node = {
            "id": new_id("n"),
            "type": "component",
            "kind": "executable",
            "name": spec.name,
            "config": config,
            "ports": [
                port.model_dump(mode="json")
                for port in merge_ports([], spec_ports(spec), set())
            ],
        }
        try:
            self.session.document.execute(AddNode(parent=params.parent, node=node))
        except CommandError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        return str(node["id"])

    def _config(
        self, params: ApplyParams | AddParams, config: dict[str, Any]
    ) -> tuple[dict[str, Any], ExecutableSpec]:
        """A component configuration using the wrapper of the parameters."""
        config = {
            key: value
            for key, value in config.items()
            if key not in ("descriptor_path", "spec", "base_folder_path")
        }
        if params.descriptor_path:
            spec = _spec(editable_spec(Path(params.descriptor_path))["spec"])
            config["descriptor_path"] = params.descriptor_path
        else:
            spec = _spec(params.spec)
            config["spec"] = spec_data(spec)
            if params.base_folder:
                config["base_folder_path"] = params.base_folder
        return config, spec

    def reveal(self, params: PathParams) -> None:
        """Open a working folder in the file manager."""
        path = Path(params.path)
        if not path.is_dir():
            msg = f"{path} does not exist any more."
            raise BridgeError(ErrorCode.NOT_FOUND, msg)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def apply(self, params: ApplyParams) -> dict[str, Any]:
        """Give a component a wrapper; its configuration and ports change together.

        One undo step restores both.
        """
        project = self.session.project
        node = project.find(params.id)
        if not isinstance(node, ComponentNode) or node.kind != "executable":
            msg = "Choose an executable component."
            raise BridgeError(ErrorCode.INVALID_PARAMS, msg)
        config, spec = self._config(params, node.config)
        linked = {
            (link.source.port, "out")
            for link in project.links
            if link.source.node == node.id
        } | {
            (link.target.port, "in")
            for link in project.links
            if link.target.node == node.id
        }
        ports = merge_ports(node.ports, spec_ports(spec), linked)
        commands: list[Command] = [
            SetNodeProperties(id=node.id, values={"config": config}),
            SetPorts(id=node.id, ports=ports),
        ]
        try:
            rev = self.session.document.execute_many(commands, "Change wrapper")
        except CommandError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        return {"rev": rev}

    def load_descriptor(self, params: PathParams) -> dict[str, Any]:
        """A descriptor to edit: its spec with inline templates, and its folder."""
        return editable_spec(Path(params.path))

    def save_descriptor(self, params: SaveParams) -> str:
        """Save a wrapper as a reusable descriptor; return its path."""
        spec = _spec(params.spec)
        return str(write_descriptor(Path(params.path), spec, params.base_folder))

    def read_sample(self, params: PathParams) -> dict[str, Any]:
        """The text of a sample file (cut beyond 5 MB)."""
        path = Path(params.path)
        try:
            with path.open("rb") as file:
                data = file.read(MAX_SAMPLE_BYTES + 1)
        except OSError as error:
            raise BridgeError(ErrorCode.NOT_FOUND, str(error)) from None
        text = data[:MAX_SAMPLE_BYTES].decode("utf-8", errors="replace")
        return {
            "name": path.name,
            # Like the wrapper reading its outputs: universal newlines.
            "text": text.replace("\r\n", "\n"),
            "truncated": len(data) > MAX_SAMPLE_BYTES,
        }

    def preview(self, params: PreviewParams) -> dict[str, Any]:
        """The value an output rule reads in a sample."""
        return preview(params.rule, params.text)

    def test_run(self, params: TestRunParams) -> Any:
        """Run the wrapper once in the worker."""
        try:
            return self.worker.call(
                "executable.test_run",
                {
                    "spec": params.spec,
                    "inputs": params.inputs,
                    "base_folder": params.base_folder,
                },
                timeout=TEST_RUN_TIMEOUT_S,
            )
        except WorkerRequestError as error:
            raise BridgeError(error.code, error.message) from None
        except WorkerUnavailableError as error:
            raise BridgeError(ErrorCode.WORKER_UNAVAILABLE, str(error)) from None

    def register(self) -> None:
        """Register the ``executable.*`` methods."""
        registry = self.bridge.registry
        registry.add("executable.loadDescriptor", self.load_descriptor)
        registry.add("executable.saveDescriptor", self.save_descriptor)
        registry.add("executable.readSample", self.read_sample)
        registry.add("executable.preview", self.preview)
        registry.add("executable.apply", self.apply)
        registry.add("executable.add", self.add)
        registry.add("executable.reveal", self.reveal)
        registry.add("executable.testRun", self.test_run, background=True)
