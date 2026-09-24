"""The introspection worker: ``python -m gemseo_process_builder.workers.introspection``.

It runs in the user's Python environment, imports GEMSEO and user code, and
answers the application's questions (catalog, ports, algorithms, dry runs…).
The application never imports GEMSEO itself (SPEC § 1.2, principle 3).

GEMSEO is imported right after startup: the worker reports
``ready`` immediately, then ``gemseo_loaded`` (or ``gemseo_failed``).
"""

import importlib
import importlib.metadata
import logging
import platform
import threading
import time
from collections.abc import Callable
from typing import Any

from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.protocol import protected_stdin
from gemseo_process_builder.workers.server import RequestContext
from gemseo_process_builder.workers.server import WorkerError
from gemseo_process_builder.workers.server import WorkerServer
from gemseo_process_builder.workers.server import setup_worker_logging

_LOGGER = logging.getLogger(__name__)

GEMSEO_TIMEOUT_S = 120.0

_gemseo_ready = threading.Event()
_gemseo_error: list[str] = []

METHOD_MODULES: list[str] = []
"""Modules defining ``register(server)``, added by later plans."""


def base_versions() -> dict[str, str]:
    """Versions known without importing GEMSEO."""
    import pydantic

    return {"python": platform.python_version(), "pydantic": pydantic.VERSION}


def _distribution_version(module: Any) -> str:
    """The installed version of a package (GEMSEO has no ``__version__``)."""
    return importlib.metadata.version(module.__name__)


def load_gemseo(channel: EventChannel) -> None:
    """Import GEMSEO and report the result."""
    try:
        import gemseo
        import numpy
    except Exception as error:
        _gemseo_error.append(f"{type(error).__name__}: {error}")
        channel.event("gemseo_failed", {"error": _gemseo_error[0]})
    else:
        channel.event(
            "gemseo_loaded",
            {"gemseo": _distribution_version(gemseo), "numpy": numpy.__version__},
        )
    finally:
        _gemseo_ready.set()


def require_gemseo(timeout: float = GEMSEO_TIMEOUT_S) -> None:
    """Wait for GEMSEO to be imported; raise if it failed."""
    if not _gemseo_ready.wait(timeout):
        raise WorkerError("worker_unavailable", "GEMSEO is still loading.")
    if _gemseo_error:
        raise WorkerError("gemseo_unavailable", f"GEMSEO failed: {_gemseo_error[0]}")


def _ping(params: dict[str, Any], context: RequestContext) -> str:
    return "pong"


def _versions(params: dict[str, Any], context: RequestContext) -> dict[str, str]:
    versions = base_versions()
    if _gemseo_ready.is_set() and not _gemseo_error:
        import gemseo

        versions["gemseo"] = _distribution_version(gemseo)
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
    # GEMSEO is imported before the request reader starts: on Windows, loading
    # numpy's DLLs hangs while another thread blocks on reading the stdin pipe.
    # Requests sent meanwhile wait in the pipe.
    load_gemseo(channel)
    server.serve(requests)


if __name__ == "__main__":
    main()
