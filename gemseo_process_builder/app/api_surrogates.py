"""Surrogate models: ``surrogates.*`` methods (SPEC § 7.4).

The worker trains the model on the results of a run and pickles it in a
training file; saving moves it into ``<project>.surrogates/`` with its
metadata. Pickles are never loaded here: the ports of surrogate components
come from the metadata.
"""

import threading
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
from gemseo_process_builder.app.worker_client import unwrap
from gemseo_process_builder.core.commands import AddNode
from gemseo_process_builder.core.commands import Command
from gemseo_process_builder.core.commands import CommandError
from gemseo_process_builder.core.commands import SetNodeProperties
from gemseo_process_builder.core.commands import SetPorts
from gemseo_process_builder.core.ids import new_id
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.ports import merge_ports
from gemseo_process_builder.results.models import read_info
from gemseo_process_builder.results.store import RunStore
from gemseo_process_builder.results.surrogates import SourceRun
from gemseo_process_builder.results.surrogates import SurrogateMetadata
from gemseo_process_builder.results.surrogates import SurrogateStore
from gemseo_process_builder.results.surrogates import SurrogateStoreError
from gemseo_process_builder.results.surrogates import SurrogateVariable
from gemseo_process_builder.results.surrogates import metadata_ports
from gemseo_process_builder.results.surrogates import now
from gemseo_process_builder.results.surrogates import read_metadata

VARIABLES_TIMEOUT_S = 60.0
TRAIN_TIMEOUT_S = 3600.0


class RunParams(BaseModel):
    """Parameters naming a run."""

    run: str


class TrainParams(BaseModel):
    """Parameters of ``surrogates.train``."""

    run: str
    inputs: list[str]
    outputs: list[str]
    algorithm: str
    settings: dict[str, Any] = {}
    n_folds: int = 5


class SaveParams(BaseModel):
    """Parameters of ``surrogates.save``: a trained model to keep."""

    trained: str
    """The training file returned by ``surrogates.train``."""

    name: str
    run: str
    algorithm: str
    settings: dict[str, Any] = {}
    result: dict[str, Any]
    """What ``surrogates.train`` returned."""

    replace: str = ""
    """The id of a surrogate to replace (retraining)."""

    node: str = ""
    """A surrogate component to use it."""


class IdParams(BaseModel):
    """Parameters naming a surrogate."""

    id: str


class UseParams(BaseModel):
    """Parameters of ``surrogates.use``."""

    node: str
    id: str


class AddParams(BaseModel):
    """Parameters of ``surrogates.add``."""

    parent: str
    id: str


def component_config(model_path: Path, metadata: SurrogateMetadata) -> dict[str, Any]:
    """The configuration of a component using a surrogate."""
    return {
        "surrogate_id": metadata.id,
        "model_path": str(model_path),
        "summary": metadata.summary(),
    }


class SurrogateController:
    """Train, store and use surrogate models."""

    def __init__(
        self,
        session: ProjectSession,
        runs: RunStore,
        bridge: Bridge,
        worker: WorkerClient,
    ) -> None:
        self.session = session
        self.runs = runs
        self.store = SurrogateStore(session)
        self.bridge = bridge
        self.worker = worker
        self._training: str | None = None
        self._cancelled = False
        runs.deleted_listeners.append(self._run_deleted)

    def _run_folder(self, run_id: str) -> Path:
        folder = self.runs.folder_of(run_id)
        if folder is None or read_info(folder) is None:
            msg = f"The run {run_id} is not available."
            raise BridgeError(ErrorCode.NOT_FOUND, msg)
        return folder

    def _changed(self) -> None:
        self.bridge.emit_event("surrogates.changed", None)

    def _run_deleted(self, run_id: str) -> None:
        if self.store.source_deleted(run_id):
            self._changed()

    # Training ------------------------------------------------------------------

    def entries(self) -> list[dict[str, Any]]:
        """The surrogates of the project with their metadata."""
        return self.store.entries()

    def variables(self, params: RunParams) -> Any:
        """The variables of a run a surrogate can use."""
        try:
            return self.worker.call(
                "surrogate.variables",
                {"folder": str(self._run_folder(params.run))},
                VARIABLES_TIMEOUT_S,
            )
        except WorkerRequestError as error:
            raise BridgeError(error.code, error.message) from None
        except WorkerUnavailableError as error:
            raise BridgeError(ErrorCode.WORKER_UNAVAILABLE, str(error)) from None

    def train(self, params: TrainParams) -> Any:
        """Train a surrogate in the worker; one at a time, cancellable."""
        if self._training is not None:
            msg = "A surrogate is already being trained."
            raise BridgeError(ErrorCode.CONFLICT, msg)
        model_file = self.store.training_file()
        done = threading.Event()
        box: dict[str, Any] = {}
        self._cancelled = False

        def store(response: dict[str, Any]) -> None:
            box.update(response)
            done.set()

        self._training = self.worker.request(
            "surrogate.train",
            {
                "folder": str(self._run_folder(params.run)),
                "inputs": params.inputs,
                "outputs": params.outputs,
                "algorithm": params.algorithm,
                "settings": params.settings,
                "n_folds": params.n_folds,
                "model_file": str(model_file),
            },
            store,
            TRAIN_TIMEOUT_S,
        )
        try:
            done.wait(TRAIN_TIMEOUT_S + 5)
            try:
                result = unwrap(box)
            except WorkerRequestError as error:
                raise BridgeError(error.code, error.message) from None
            except WorkerUnavailableError as error:
                if self._cancelled:
                    msg = "The training was cancelled."
                    raise BridgeError(ErrorCode.CANCELLED, msg) from None
                raise BridgeError(ErrorCode.WORKER_UNAVAILABLE, str(error)) from None
            return {**result, "trained": str(model_file)}
        finally:
            self._training = None

    def cancel(self) -> None:
        """Stop the training by restarting the worker."""
        if self._training is not None:
            self._cancelled = True
            self.worker.restart()

    # Storage -------------------------------------------------------------------

    def save(self, params: SaveParams) -> dict[str, Any]:
        """Keep a trained surrogate; the components using it follow."""
        trained = Path(params.trained)
        training_folder = self.store.folder() / ".training"
        if trained.parent.resolve() != training_folder.resolve():
            msg = "Only a model trained by surrogates.train can be saved."
            raise BridgeError(ErrorCode.INVALID_PARAMS, msg)
        name = params.name.strip()
        if not name:
            raise BridgeError(ErrorCode.INVALID_PARAMS, "Give the surrogate a name.")
        info = read_info(self._run_folder(params.run))
        result = params.result
        stamp = now()
        metadata = SurrogateMetadata(
            id=new_id("s"),
            name=name,
            algorithm=params.algorithm,
            settings=params.settings,
            source=SourceRun(
                id=params.run,
                name=info.name if info else "",
                driver_name=info.driver_name if info else "",
            ),
            inputs=[
                SurrogateVariable.model_validate(item) for item in result["inputs"]
            ],
            outputs=[
                SurrogateVariable.model_validate(item) for item in result["outputs"]
            ],
            n_samples=result["n_samples"],
            n_folds=result["n_folds"],
            quality=result["quality"],
            created=stamp,
            updated=stamp,
        )
        try:
            path = self.store.save(trained, metadata, params.replace)
        except SurrogateStoreError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        saved = read_metadata(path) or metadata
        users = [
            node.id
            for node, _ in iter_nodes(self.session.project.root)
            if isinstance(node, ComponentNode)
            and node.kind == "surrogate"
            and node.config.get("surrogate_id") == saved.id
        ]
        if params.node and params.node not in users:
            users.append(params.node)
        if users:
            self._use(users, path, saved)
        self.store.discard_training()
        self._changed()
        return {"id": saved.id, "model_path": str(path)}

    def _use(
        self, node_ids: list[str], path: Path, metadata: SurrogateMetadata
    ) -> None:
        """Make components use a surrogate: configuration and ports in one step."""
        project = self.session.project
        commands: list[Command] = []
        for node_id in node_ids:
            node = project.find(node_id)
            if not isinstance(node, ComponentNode) or node.kind != "surrogate":
                msg = "Choose a surrogate component."
                raise BridgeError(ErrorCode.INVALID_PARAMS, msg)
            linked = {
                (link.source.port, "out")
                for link in project.links
                if link.source.node == node.id
            } | {
                (link.target.port, "in")
                for link in project.links
                if link.target.node == node.id
            }
            ports = merge_ports(node.ports, metadata_ports(metadata), linked)
            config = {**node.config, **component_config(path, metadata)}
            commands.append(SetNodeProperties(id=node.id, values={"config": config}))
            commands.append(SetPorts(id=node.id, ports=ports))
        try:
            self.session.document.execute_many(commands, "Use surrogate")
        except CommandError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None

    def _stored(self, surrogate_id: str) -> tuple[Path, SurrogateMetadata]:
        try:
            path = self.store.model_path(self.store.ref(surrogate_id))
        except SurrogateStoreError as error:
            raise BridgeError(ErrorCode.NOT_FOUND, str(error)) from None
        metadata = read_metadata(path)
        if metadata is None:
            msg = f"The metadata of {path.name} is missing."
            raise BridgeError(ErrorCode.NOT_FOUND, msg)
        return path, metadata

    def use(self, params: UseParams) -> None:
        """Make a surrogate component use a surrogate of the project."""
        path, metadata = self._stored(params.id)
        self._use([params.node], path, metadata)

    def add(self, params: AddParams) -> str:
        """Add a component using a surrogate; return its id."""
        path, metadata = self._stored(params.id)
        node = {
            "id": new_id("n"),
            "type": "component",
            "kind": "surrogate",
            "name": metadata.name,
            "config": component_config(path, metadata),
            "ports": [
                port.model_dump(mode="json")
                for port in merge_ports([], metadata_ports(metadata), set())
            ],
        }
        try:
            self.session.document.execute(AddNode(parent=params.parent, node=node))
        except CommandError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        return str(node["id"])

    def delete(self, params: IdParams) -> None:
        """Delete a surrogate and its files (the page asks for confirmation)."""
        try:
            self.store.delete(params.id)
        except SurrogateStoreError as error:
            raise BridgeError(ErrorCode.NOT_FOUND, str(error)) from None
        self._changed()

    def register(self) -> None:
        """Register the ``surrogates.*`` methods."""
        registry = self.bridge.registry
        registry.add("surrogates.list", self.entries)
        registry.add("surrogates.variables", self.variables, background=True)
        registry.add("surrogates.train", self.train, background=True)
        registry.add("surrogates.cancel", self.cancel)
        registry.add("surrogates.save", self.save)
        registry.add("surrogates.use", self.use)
        registry.add("surrogates.add", self.add)
        registry.add("surrogates.delete", self.delete)
