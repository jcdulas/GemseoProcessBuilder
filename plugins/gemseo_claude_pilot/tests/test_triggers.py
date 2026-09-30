from gemseo_claude_pilot.detectors import Event
from gemseo_claude_pilot.triggers import Triggers
from gemseo_claude_pilot.triggers import TriggerSettings

STAGNATION = Event("stagnation", "Nothing moves.", 9)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def triggers(**settings):
    clock = Clock()
    return Triggers(TriggerSettings(**settings), clock), clock


def test_periodic():
    checks, _ = triggers(period=10, min_interval=0)
    assert checks.due(9, []) == (None, [])
    assert checks.due(10, []) == ("periodic", [])
    assert checks.due(15, []) == (None, [])
    assert checks.due(20, []) == ("periodic", [])


def test_periodic_in_seconds():
    checks, clock = triggers(period=None, period_seconds=60, min_interval=0)
    checks.called(0)
    clock.now = 59
    assert checks.due(3, []) == (None, [])
    clock.now = 60
    assert checks.due(4, []) == ("periodic", [])


def test_minimum_interval_delays_events():
    checks, clock = triggers(period=None, min_interval=30)
    checks.called(0)
    clock.now = 10
    assert checks.due(5, [STAGNATION]) == (None, [])
    clock.now = 31
    assert checks.due(6, [STAGNATION]) == ("event", [STAGNATION])


def test_an_event_is_reported_once_while_it_lasts():
    checks, _ = triggers(period=None, min_interval=0)
    assert checks.due(10, [STAGNATION]) == ("event", [STAGNATION])
    assert checks.due(11, [STAGNATION]) == (None, [])
    assert checks.due(12, []) == (None, [])
    assert checks.due(13, [STAGNATION]) == ("event", [STAGNATION])


def test_new_failures_are_always_reported():
    checks, _ = triggers(period=None, min_interval=0)
    failure = Event("failed_evaluations", "1 evaluation(s) failed", 3)
    assert checks.due(4, [failure]) == ("event", [failure])
    assert checks.failures_since == 4


def test_events_off():
    checks, _ = triggers(period=None, events=False, min_interval=0)
    assert checks.due(10, [STAGNATION]) == (None, [])


def test_forced_calls_take_the_waiting_events():
    checks, clock = triggers(period=None, min_interval=30)
    checks.called(0)
    clock.now = 1
    checks.due(3, [STAGNATION])
    assert checks.forced(4, [STAGNATION]) == [STAGNATION]
    clock.now = 100
    assert checks.due(5, [STAGNATION]) == (None, [])
