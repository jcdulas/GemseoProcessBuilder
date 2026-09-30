"""A lightweight worker for client tests: no GEMSEO, fast to start."""

import os
import platform
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.server import RequestContext
from gemseo_process_builder.workers.server import WorkerServer


def echo(params: dict[str, Any], context: RequestContext) -> Any:
    print("noise that must not break the protocol")
    return params.get("value")


def sleep(params: dict[str, Any], context: RequestContext) -> None:
    import time

    end = time.monotonic() + float(params["seconds"])
    while time.monotonic() < end:
        context.check()
        time.sleep(0.01)


def crash(params: dict[str, Any], context: RequestContext) -> None:
    os._exit(3)


def main() -> None:
    channel = EventChannel()
    server = WorkerServer(channel)
    server.add("echo", echo)
    server.add("sleep", sleep)
    server.add("crash", crash)
    gemseo = sys.argv[1] if len(sys.argv) > 1 else "6.0.0"
    channel.event("ready", {"python": platform.python_version(), "pydantic": "2.11.0"})
    channel.event("gemseo_loaded", {"gemseo": gemseo})
    server.serve()


if __name__ == "__main__":
    main()
