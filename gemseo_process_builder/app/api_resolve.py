"""Coupling resolution for the page: ``resolve.*`` methods.

The resolution is computed on demand and cached for the current document
revision. After each document change, a ``resolution.updated`` event tells the
views to ask again.
"""

from typing import Any

from pydantic import BaseModel

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.core.document import Change
from gemseo_process_builder.core.resolver import Resolution
from gemseo_process_builder.core.resolver import level_view
from gemseo_process_builder.core.resolver import resolve
from gemseo_process_builder.core.units import check
from gemseo_process_builder.core.units import suggestions


class LevelParams(BaseModel):
    """Parameters of ``resolve.level``."""

    level: str


class LevelsParams(BaseModel):
    """Parameters of ``resolve.levels``."""

    levels: list[str]


class NodeParams(BaseModel):
    """Parameters of ``resolve.node``."""

    id: str


class UnitsParams(BaseModel):
    """Parameters of ``units.check``."""

    source: str | None
    target: str | None


class PrefixParams(BaseModel):
    """Parameters of ``units.suggestions``."""

    prefix: str = ""


class ResolutionService:
    """Cache the resolution of the current document revision."""

    def __init__(self, session: ProjectSession, bridge: Bridge) -> None:
        self.session = session
        self.bridge = bridge
        self._cache: tuple[int, Any, Resolution] | None = None
        session.document.on_change(self._changed)

    def current(self) -> Resolution:
        """The resolution of the current project and revision."""
        document = self.session.document
        key = (document.rev, id(document.project))
        if self._cache is None or self._cache[:2] != key:
            self._cache = (*key, resolve(document.project))
        return self._cache[2]

    def _changed(self, changes: list[Change], rev: int) -> None:
        if any(change["kind"] in ("node", "link") for change in changes):
            self.bridge.emit_event("resolution.updated", {"rev": rev})

    def level(self, params: LevelParams) -> dict[str, Any]:
        """Couplings between the nodes of a level (``resolve.level``)."""
        return level_view(self.current(), self.session.project, params.level)

    def levels(self, params: LevelsParams) -> dict[str, Any]:
        """Couplings of several levels at once (``resolve.levels``)."""
        resolution = self.current()
        return {
            "rev": self.session.document.rev,
            "views": {
                level: level_view(resolution, self.session.project, level)
                for level in params.levels
            },
        }

    def node(self, params: NodeParams) -> dict[str, Any]:
        """Global names and couplings of a component's ports (``resolve.node``)."""
        resolution = self.current()
        scope = resolution.scope_of.get(params.id, "")
        couplings = resolution.couplings.get(scope, {})
        ports = []
        for ref, resolved in resolution.ports.items():
            if ref.node != params.id:
                continue
            coupling = couplings.get(resolved.global_name)
            if ref.direction == "in":
                partners = [p.node for p in coupling.producers] if coupling else []
            else:
                partners = [c.node for c, _ in coupling.consumers] if coupling else []
            ports.append(
                {
                    "name": ref.port,
                    "direction": ref.direction,
                    "global_name": resolved.global_name,
                    "source": resolved.source,
                    "partners": partners,
                }
            )
        return {"id": params.id, "scope": scope, "ports": ports}

    def couplings(self) -> dict[str, Any]:
        """All couplings by scope, and the free inputs (``resolve.couplings``)."""
        resolution = self.current()
        return {
            scope: {
                "free_inputs": resolution.free_inputs.get(scope, []),
                "couplings": {
                    name: {
                        "producers": [ref.__dict__ for ref in coupling.producers],
                        "consumers": [
                            {**ref.__dict__, "kind": kind}
                            for ref, kind in coupling.consumers
                        ],
                    }
                    for name, coupling in couplings.items()
                },
            }
            for scope, couplings in resolution.couplings.items()
        }

    def check_units(self, params: UnitsParams) -> dict[str, Any]:
        """How a value in one unit feeds a variable in another (``units.check``)."""
        return check(params.source, params.target).to_dict()

    def unit_suggestions(self, params: PrefixParams) -> list[str]:
        """Common units starting with a prefix (``units.suggestions``)."""
        return suggestions(params.prefix, limit=100)

    def register(self) -> None:
        """Register the ``resolve.*`` and ``units.*`` methods."""
        registry = self.bridge.registry
        registry.add("units.check", self.check_units)
        registry.add("units.suggestions", self.unit_suggestions)
        registry.add("resolve.level", self.level)
        registry.add("resolve.levels", self.levels)
        registry.add("resolve.node", self.node)
        registry.add("resolve.couplings", self.couplings)
