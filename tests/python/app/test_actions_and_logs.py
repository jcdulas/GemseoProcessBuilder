import json
import logging

from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QMainWindow

from gemseo_process_builder.app.actions import ACTIONS
from gemseo_process_builder.app.actions import MENUS
from gemseo_process_builder.app.actions import ActionStatesParams
from gemseo_process_builder.app.actions import NativeMenus
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.log_forwarding import LogForwarder
from gemseo_process_builder.app.log_forwarding import RateLimiter


def test_action_ids_and_shortcuts_are_unique() -> None:
    ids = [action.id for action in ACTIONS]
    shortcuts = [shortcut for action in ACTIONS for shortcut in action.shortcuts]
    assert len(ids) == len(set(ids))
    assert len(shortcuts) == len(set(shortcuts))
    assert {action.menu for action in ACTIONS} <= set(MENUS)


def test_native_menus_forward_clicks_and_follow_states() -> None:
    bridge = Bridge(MethodRegistry())
    events: list[str] = []
    bridge.page_event.connect(events.append)
    window = QMainWindow()
    menus = NativeMenus(window, bridge)

    assert not menus.actions["edit.undo"].isEnabled()
    menus.set_states(ActionStatesParams(enabled={"edit.undo": True}))
    assert menus.actions["edit.undo"].isEnabled()
    assert menus.actions["edit.undo"].text() == "Undo\tCtrl+Z"

    menus.actions["edit.undo"].trigger()
    assert json.loads(events[0]) == {
        "type": "action.invoke",
        "payload": {"id": "edit.undo"},
    }
    menus.set_states(ActionStatesParams(checked={"view.toggleLeft": False}))
    assert not menus.actions["view.toggleLeft"].isChecked()
    window.deleteLater()


def test_rate_limiter() -> None:
    limiter = RateLimiter(2)
    assert [limiter.allow(0.1), limiter.allow(0.2), limiter.allow(0.3)] == [
        True,
        True,
        False,
    ]
    assert limiter.take_dropped() == 1
    assert limiter.allow(1.2)
    assert limiter.take_dropped() == 0


def test_log_forwarder_pushes_records_and_keeps_history() -> None:
    bridge = Bridge(MethodRegistry())
    events: list[str] = []
    bridge.page_event.connect(events.append)
    forwarder = LogForwarder(bridge)
    logger = logging.getLogger("gemseo_process_builder.test_forwarder")
    logger.addHandler(forwarder)
    logger.setLevel(logging.INFO)
    try:
        logger.warning("Hello %s", "world")
        QApplication.processEvents()
    finally:
        logger.removeHandler(forwarder)
    event = json.loads(events[-1])
    assert event["type"] == "app.log"
    assert event["payload"]["message"] == "Hello world"
    assert event["payload"]["level"] == "WARNING"
    assert forwarder.history[-1]["message"] == "Hello world"
