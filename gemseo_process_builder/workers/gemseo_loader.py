"""Loading of GEMSEO in a worker, shared by the worker methods.

This state lives in its own module: the worker entry point runs as
``__main__``, and state kept there would be duplicated when method modules
import it by name.
"""

import importlib.metadata
import threading
from typing import Any

from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.server import WorkerError

GEMSEO_TIMEOUT_S = 120.0

_ready = threading.Event()
_errors: list[str] = []


def distribution_version(module: Any) -> str:
    """The installed version of a package (GEMSEO has no ``__version__``)."""
    return importlib.metadata.version(module.__name__)


def load_gemseo(channel: EventChannel) -> None:
    """Import GEMSEO and report ``gemseo_loaded`` or ``gemseo_failed``."""
    try:
        import gemseo
        import numpy
    except Exception as error:
        _errors.append(f"{type(error).__name__}: {error}")
        channel.event("gemseo_failed", {"error": _errors[0]})
    else:
        channel.event(
            "gemseo_loaded",
            {"gemseo": distribution_version(gemseo), "numpy": numpy.__version__},
        )
    finally:
        _ready.set()


def gemseo_loaded() -> bool:
    """Whether GEMSEO was imported successfully."""
    return _ready.is_set() and not _errors


def require_gemseo(timeout: float = GEMSEO_TIMEOUT_S) -> None:
    """Wait for GEMSEO to be imported; raise if it failed."""
    if not _ready.wait(timeout):
        raise WorkerError("worker_unavailable", "GEMSEO is still loading.")
    if _errors:
        raise WorkerError("gemseo_unavailable", f"GEMSEO failed: {_errors[0]}")
