import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication

from gemseo_process_builder.app.worker_client import WorkerClient
from gemseo_process_builder.app.worker_client import check_versions
from gemseo_process_builder.app.worker_client import unwrap

FAKE_WORKER = str(Path(__file__).parents[1] / "workers" / "fake_worker.py")


def wait_until(condition: Callable[[], bool], timeout: float = 0.8) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture
def client() -> Any:
    client = WorkerClient(arguments=[FAKE_WORKER])
    states: list[str] = []
    client.status_changed.connect(lambda status: states.append(status["state"]))
    client.states = states  # type: ignore[attr-defined]
    client.start()
    yield client
    client.stop()


def test_request_and_response(client: WorkerClient) -> None:
    responses: list[dict[str, Any]] = []
    client.request("echo", {"value": {"a": [1, 2]}}, responses.append)
    assert wait_until(lambda: bool(responses))
    assert unwrap(responses[0]) == {"a": [1, 2]}
    assert wait_until(lambda: client.status.state == "ready")
    assert client.status.versions["gemseo"] == "6.0.0"


def test_error_response(client: WorkerClient) -> None:
    responses: list[dict[str, Any]] = []
    client.request("nope", {}, responses.append)
    assert wait_until(lambda: bool(responses))
    assert responses[0]["error"]["code"] == "unknown_method"


def test_timeout_restarts_the_worker(client: WorkerClient) -> None:
    responses: list[dict[str, Any]] = []
    client.request("sleep", {"seconds": 5}, responses.append, timeout=0.1)
    assert wait_until(lambda: bool(responses))
    assert responses[0]["error"]["code"] == "worker_unavailable"
    assert wait_until(lambda: client.status.state == "ready")
    assert "starting" in client.states  # type: ignore[attr-defined]


def test_crash_restarts_the_worker(client: WorkerClient) -> None:
    responses: list[dict[str, Any]] = []
    client.request("crash", {}, responses.append)
    assert wait_until(lambda: bool(responses))
    assert responses[0]["error"]["code"] == "worker_unavailable"
    assert wait_until(lambda: client.status.state == "ready")


def test_restart_limit(client: WorkerClient) -> None:
    import gemseo_process_builder.app.worker_client as module

    original = module.MAX_RESTARTS
    module.MAX_RESTARTS = 1
    try:
        assert wait_until(lambda: client.status.state == "ready")
        client.request("crash", {})
        assert wait_until(lambda: client.status.state == "starting")
        assert wait_until(lambda: client.status.state == "ready")
        client.request("crash", {})
        assert wait_until(lambda: client.status.state == "crashed")
    finally:
        module.MAX_RESTARTS = original


def test_incompatible_gemseo() -> None:
    client = WorkerClient(arguments=[FAKE_WORKER, "5.3.0"])
    client.start()
    try:
        assert wait_until(lambda: client.status.state == "incompatible")
        assert "GEMSEO 5.3.0" in client.status.detail
    finally:
        client.stop()


def test_missing_interpreter() -> None:
    client = WorkerClient(interpreter=str(Path(sys.executable).parent / "nope.exe"))
    client.start()
    try:
        assert wait_until(lambda: client.status.state == "crashed")
        assert "interpreter" in client.status.detail
    finally:
        client.stop()


@pytest.mark.parametrize(
    ("versions", "problem"),
    [
        ({"python": "3.12.5", "pydantic": "2.11.0", "gemseo": "6.3.3"}, ""),
        ({"python": "3.12.5", "pydantic": "2.11.0"}, ""),
        ({"python": "3.11.2", "pydantic": "2.11.0"}, "too old"),
        ({"python": "3.12.0", "pydantic": "1.10.0"}, "Pydantic"),
        ({"python": "3.12.0", "pydantic": "2.1", "gemseo": "5.3.0"}, "GEMSEO"),
    ],
)
def test_check_versions(versions: dict[str, str], problem: str) -> None:
    result = check_versions(versions)
    assert (problem in result) if problem else result == ""
