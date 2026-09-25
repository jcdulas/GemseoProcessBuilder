"""The derivatives of the model for the page: ``derivatives.*`` methods.

Both methods build the generated scripts in the worker (GEMSEO and user code
never run in the window): ``derivatives.origins`` tells where the derivatives of
each component come from, ``derivatives.check`` compares the derivatives of a
node with finite differences.
"""

from typing import Any

from pydantic import BaseModel

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.app.validation_service import dry_run_targets
from gemseo_process_builder.app.worker_client import WorkerClient
from gemseo_process_builder.app.worker_client import WorkerRequestError
from gemseo_process_builder.app.worker_client import WorkerUnavailableError
from gemseo_process_builder.codegen.generator import CodegenError
from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.core.model import ComponentNode

ORIGINS_TIMEOUT_S = 60
CHECK_TIMEOUT_S = 600


class NodeParams(BaseModel):
    """Parameters of ``derivatives.check``."""

    node: str


class DerivativesService:
    """Where the derivatives come from, and whether they are right."""

    def __init__(
        self, session: ProjectSession, bridge: Bridge, worker: WorkerClient
    ) -> None:
        self.session = session
        self.bridge = bridge
        self.worker = worker

    def _call(self, method: str, params: dict[str, Any], timeout: float) -> Any:
        try:
            return self.worker.call(method, params, timeout=timeout)
        except WorkerUnavailableError as error:
            raise BridgeError(ErrorCode.WORKER_UNAVAILABLE, str(error)) from None
        except WorkerRequestError as error:
            raise BridgeError(ErrorCode.INTERNAL, str(error)) from None

    def origins(self) -> dict[str, Any]:
        """The origin of the derivatives of each node (``derivatives.origins``).

        By node id: ``exact``, ``approximated`` or ``missing``.
        """
        project = self.session.project
        found: dict[str, str] = {}
        for target in dry_run_targets(project):
            try:
                script = generate(project, target.id)
            except CodegenError:
                continue  # Reported by the validation.
            try:
                found.update(
                    self._call(
                        "derivatives.origins",
                        {"source": script.source, "mapping": script.mapping},
                        ORIGINS_TIMEOUT_S,
                    )
                )
            except BridgeError as error:
                if error.code == ErrorCode.WORKER_UNAVAILABLE:
                    raise
                # A script that cannot be built: the dry run reports why.
        return {"rev": self.session.document.rev, "origins": found}

    def check(self, params: NodeParams) -> dict[str, Any]:
        """Compare the derivatives of a node with finite differences.

        This is ``derivatives.check``. A driver is checked through its whole
        process: the derivatives of its objective and constraints with respect to
        its design variables. A group is checked as a whole, a component alone.
        """
        project = self.session.project
        node = project.find(params.node)
        if node is None:
            raise BridgeError(ErrorCode.NOT_FOUND, f"No node {params.node}.")
        target = project.parent_of(node.id) if isinstance(node, ComponentNode) else node
        if target is None:
            raise BridgeError(ErrorCode.NOT_FOUND, f"{node.name} has no parent.")
        try:
            script = generate(project, target.id)
        except CodegenError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        discipline = ""
        if isinstance(node, ComponentNode):
            discipline = script.mapping.get("disciplines", {}).get(node.id, node.name)
        result = self._call(
            "derivatives.check",
            {
                "source": script.source,
                "mapping": script.mapping,
                "discipline": discipline,
            },
            CHECK_TIMEOUT_S,
        )
        return {"node": node.id, "name": node.name, **result}

    def register(self) -> None:
        """Register the ``derivatives.*`` methods."""
        registry = self.bridge.registry
        registry.add("derivatives.origins", self.origins, background=True)
        registry.add("derivatives.check", self.check, background=True)
