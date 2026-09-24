import json
from typing import Any

import pytest
from pydantic import BaseModel
from PySide6.QtCore import QEventLoop
from PySide6.QtCore import QTimer

from gemseo_process_builder.app.api_app import register_app_methods
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import MethodRegistry


class AddParams(BaseModel):
    a: int
    b: int


def add(params: AddParams) -> int:
    return params.a + params.b


def fail() -> None:
    msg = "boom"
    raise RuntimeError(msg)


@pytest.fixture
def registry() -> MethodRegistry:
    registry = MethodRegistry()
    register_app_methods(registry)
    registry.add("math.add", add)
    registry.add("math.add_later", add, background=True)
    registry.add("fail", fail)
    return registry


@pytest.fixture
def bridge(registry: MethodRegistry) -> Bridge:
    return Bridge(registry)


def call(bridge: Bridge, request: dict[str, Any] | str) -> dict[str, Any]:
    replies: list[str] = []
    bridge.reply.connect(replies.append)
    bridge.call(request if isinstance(request, str) else json.dumps(request))
    assert len(replies) == 1
    return json.loads(replies[0])


def test_sync_method(bridge: Bridge) -> None:
    reply = call(bridge, {"id": "1", "method": "math.add", "params": {"a": 2, "b": 3}})
    assert reply == {"id": "1", "ok": True, "result": 5}


def test_method_without_params(bridge: Bridge) -> None:
    assert call(bridge, {"id": "p", "method": "app.ping"})["result"] == "pong"


def test_unknown_method(bridge: Bridge) -> None:
    reply = call(bridge, {"id": "2", "method": "nope"})
    assert reply["ok"] is False
    assert reply["id"] == "2"
    assert reply["error"]["code"] == "unknown_method"


def test_invalid_params(bridge: Bridge) -> None:
    reply = call(bridge, {"id": "3", "method": "math.add", "params": {"a": "x"}})
    assert reply["error"]["code"] == "invalid_params"
    assert {tuple(e["loc"]) for e in reply["error"]["details"]} == {("a",), ("b",)}


def test_params_given_to_method_without_params(bridge: Bridge) -> None:
    reply = call(bridge, {"id": "4", "method": "app.ping", "params": {"x": 1}})
    assert reply["error"]["code"] == "invalid_params"


def test_invalid_request(bridge: Bridge) -> None:
    reply = call(bridge, "not json")
    assert reply["error"]["code"] == "invalid_request"
    assert reply["id"] == ""


def test_handler_exception_is_internal_without_traceback(bridge: Bridge) -> None:
    reply = call(bridge, {"id": "5", "method": "fail"})
    assert reply["error"]["code"] == "internal"
    assert reply["error"]["message"] == "boom"
    assert reply["error"]["details"] is None


def test_traceback_in_dev_mode(registry: MethodRegistry) -> None:
    reply = call(Bridge(registry, dev_mode=True), {"id": "6", "method": "fail"})
    assert "RuntimeError" in "".join(reply["error"]["details"])


def test_background_method(bridge: Bridge) -> None:
    replies: list[str] = []
    loop = QEventLoop()
    bridge.reply.connect(replies.append)
    bridge.reply.connect(loop.quit)
    QTimer.singleShot(500, loop.quit)
    bridge.call(
        json.dumps({"id": "7", "method": "math.add_later", "params": {"a": 1, "b": 1}})
    )
    loop.exec()
    assert json.loads(replies[0]) == {"id": "7", "ok": True, "result": 2}


def test_event_payload(bridge: Bridge) -> None:
    events: list[str] = []
    bridge.page_event.connect(events.append)
    bridge.emit_event("document.patch", {"rev": 3})
    assert json.loads(events[0]) == {"type": "document.patch", "payload": {"rev": 3}}


def test_duplicate_registration(registry: MethodRegistry) -> None:
    with pytest.raises(ValueError, match="already registered"):
        registry.add("math.add", add)


def test_handler_parameter_must_be_a_model(registry: MethodRegistry) -> None:
    def bad(value: int) -> int:
        return value

    with pytest.raises(TypeError, match="Pydantic model"):
        registry.add("bad", bad)
