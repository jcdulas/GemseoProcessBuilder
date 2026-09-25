"""The introspection worker: ``python -m gemseo_process_builder.workers.introspection``.

It runs in the user's Python environment, imports GEMSEO and user code, and
answers the application's questions (catalog, ports, algorithms, dry runs…).
The application never imports GEMSEO itself (SPEC § 1.2, principle 3).

The worker reports ``ready`` immediately, then imports GEMSEO and reports
``gemseo_loaded`` (or ``gemseo_failed``) before serving requests.
"""

import importlib
import logging
import platform
import time
from collections.abc import Callable
from typing import Any

from gemseo_process_builder.workers.gemseo_loader import distribution_version
from gemseo_process_builder.workers.gemseo_loader import gemseo_loaded
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.protocol import protected_stdin
from gemseo_process_builder.workers.server import RequestContext
from gemseo_process_builder.workers.server import WorkerServer
from gemseo_process_builder.workers.server import setup_worker_logging

_LOGGER = logging.getLogger(__name__)

METHOD_MODULES: list[str] = [
    "gemseo_process_builder.catalog.scanner",
    "gemseo_process_builder.workers.component_methods",
    "gemseo_process_builder.workers.algorithms_methods",
    "gemseo_process_builder.workers.codegen_methods",
    "gemseo_process_builder.workers.results_methods",
    "gemseo_process_builder.workers.postproc_methods",
    "gemseo_process_builder.workers.xdsm_methods",
    "gemseo_process_builder.workers.executable_methods",
    "gemseo_process_builder.workers.surrogate_methods",
    "gemseo_process_builder.workers.derivatives_methods",
]
"""Modules defining ``register(server)``, added by later plans."""


def base_versions() -> dict[str, str]:
    """Versions known without importing GEMSEO."""
    import pydantic

    return {"python": platform.python_version(), "pydantic": pydantic.VERSION}


def _ping(params: dict[str, Any], context: RequestContext) -> str:
    return "pong"


def _versions(params: dict[str, Any], context: RequestContext) -> dict[str, str]:
    versions = base_versions()
    if gemseo_loaded():
        import gemseo

        versions["gemseo"] = distribution_version(gemseo)
    return versions


def _sleep(params: dict[str, Any], context: RequestContext) -> float:
    """Sleep in small steps, checking for cancellation (used by tests)."""
    duration = float(params.get("seconds", 0.0))
    end = time.monotonic() + duration
    while time.monotonic() < end:
        context.check()
        time.sleep(min(0.01, max(0.0, end - time.monotonic())))
    return duration


def build_server(
    channel: EventChannel,
    extra_modules: list[str] | None = None,
) -> WorkerServer:
    """Create the server with the built-in methods and the method modules."""
    server = WorkerServer(channel)
    server.add("worker.ping", _ping)
    server.add("worker.versions", _versions)
    server.add("worker.sleep", _sleep)
    for module_name in [*METHOD_MODULES, *(extra_modules or [])]:
        register: Callable[[WorkerServer], None] = importlib.import_module(
            module_name
        ).register
        register(server)
    return server


def main() -> None:
    """Run the worker until the application closes its stdin."""
    channel = EventChannel()
    requests = protected_stdin()
    setup_worker_logging(channel)
    server = build_server(channel)
    channel.event("ready", base_versions())
    load_gemseo(channel)
    server.serve(requests)


if __name__ == "__main__":
    main()
