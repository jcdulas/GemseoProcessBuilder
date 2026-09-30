"""Worker methods: ``worker.*``, and the ``worker.status`` event."""

from typing import Any

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.worker_client import WorkerClient


def register_worker_methods(bridge: Bridge, worker: WorkerClient) -> None:
    """Register ``worker.status`` and ``worker.restart``; forward status changes."""

    def status() -> dict[str, Any]:
        return worker.status.to_dict()

    def restart() -> dict[str, Any]:
        worker.restart()
        return worker.status.to_dict()

    bridge.registry.add("worker.status", status)
    bridge.registry.add("worker.restart", restart)
    worker.status_changed.connect(lambda data: bridge.emit_event("worker.status", data))
