"""The N2 matrix of a level for the page: ``n2.build`` (SPEC § 8.4).

The matrix comes from the resolution of the current document revision, in the
UI process: GEMSEO is not needed.
"""

from typing import Any

from pydantic import BaseModel

from gemseo_process_builder.app.api_resolve import ResolutionService
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.core.n2 import n2_matrix


class LevelParams(BaseModel):
    """Parameters of ``n2.build``."""

    level: str


def register_n2_methods(bridge: Bridge, resolution: ResolutionService) -> None:
    """Register ``n2.build``."""

    def build(params: LevelParams) -> dict[str, Any]:
        """The N2 matrix of a level, fully expanded."""
        return n2_matrix(resolution.session.project, resolution.current(), params.level)

    bridge.registry.add("n2.build", build)
