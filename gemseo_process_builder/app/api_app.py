"""General application methods: ``app.*``."""

from typing import Any

from pydantic import BaseModel

from gemseo_process_builder import __version__
from gemseo_process_builder.app.bridge import MethodRegistry


class EchoParams(BaseModel):
    """Parameters of ``app.echo``."""

    value: Any = None


def ping() -> str:
    """Answer ``"pong"``; used to check that the bridge works."""
    return "pong"


def version() -> dict[str, str]:
    """Return the application version."""
    return {"version": __version__}


def echo(params: EchoParams) -> Any:
    """Return the value it receives; used by tests and the dev console."""
    return params.value


def register_app_methods(registry: MethodRegistry) -> None:
    """Register the ``app.*`` methods."""
    registry.add("app.ping", ping)
    registry.add("app.version", version)
    registry.add("app.echo", echo)
