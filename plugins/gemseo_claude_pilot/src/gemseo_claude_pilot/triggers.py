"""When to call Claude during a segment (spec § 4.2).

Periodic calls and events share a minimum interval; events that appear
meanwhile wait and are reported together with the next call. An event is
reported when it appears, not again while it lasts. The start and end calls
are made by the pilot between segments, outside these rules.
"""

import time
from collections.abc import Callable
from collections.abc import Sequence
from dataclasses import dataclass

from gemseo_claude_pilot.context import TriggerKind
from gemseo_claude_pilot.detectors import Event


@dataclass(frozen=True)
class TriggerSettings:
    """Which triggers are on, and how often they fire."""

    period: int | None = 25
    """Evaluations between two periodic calls; ``None`` turns them off."""

    period_seconds: float | None = None
    """Seconds between two periodic calls, for slow evaluations."""

    period_iterations: int | None = 10
    """Outer iterations between two periodic calls, for an algorithm that
    reports them (``LSO_MMA``, ``LSO_GCMMA``): GCMMA's inner iterations and the
    repairs make the evaluations a poor clock."""

    answer_pause: float | None = 10.0
    """For an algorithm reporting its outer iterations: seconds after the end
    of the last answer of Claude from which the next outer iteration calls it
    again, whatever ``period_iterations``; ``None`` turns it off. With a model
    answering in seconds, Claude follows the run nearly all the time."""

    first_iteration: bool = True
    """For an algorithm reporting its outer iterations: call Claude after the
    first one, to judge whether the run started from a viable point."""

    events: bool = True
    """Whether the detectors' events trigger a call."""

    start: bool = True
    """Whether Claude reviews the problem before the first segment."""

    end: bool = True
    """Whether Claude is called when a segment ends by itself."""

    min_interval: float = 30.0
    """Seconds between two periodic or event calls."""

    check_every: int = 5
    """Evaluations between two checks of the triggers."""


class Triggers:
    """Decides, at each check, whether Claude must be called.

    Args:
        settings: The triggers.
        clock: The time in seconds, for the tests.
    """

    def __init__(
        self,
        settings: TriggerSettings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._clock = clock
        self._last_evaluation = 0
        self._last_iteration = 0
        self._last_time: float | None = None
        self._last_answer: float | None = None
        self._active: set[str] = set()
        self._waiting: list[Event] = []
        self.failures_since = 0
        """The first evaluation whose failures were not reported yet."""

    def called(self, n_evaluations: int, iteration: int = 0) -> None:
        """Note a call to Claude, whatever its trigger."""
        self._last_evaluation = n_evaluations
        self._last_iteration = iteration
        self._last_time = self._clock()

    def answered(self) -> None:
        """Note the end of a call, answered or failed."""
        self._last_answer = self._clock()

    def due(
        self, n_evaluations: int, events: Sequence[Event], iteration: int = 0
    ) -> tuple[TriggerKind | None, list[Event]]:
        """The trigger that fires now, if any, and the events to report.

        Args:
            n_evaluations: The evaluations made.
            events: The symptoms the run shows now.
            iteration: The outer iteration of an algorithm that reports them;
                0 otherwise.
        """
        self._waiting += self._new(events, n_evaluations)
        now = self._clock()
        settings = self.settings
        if (
            self._last_time is not None
            and now - self._last_time < settings.min_interval
        ):
            return None, []
        evaluations = n_evaluations - self._last_evaluation
        seconds = now - (self._last_time or 0.0)
        iterations = iteration - self._last_iteration
        pause = settings.answer_pause
        periodic = bool(
            (settings.period and evaluations >= settings.period)
            or (settings.period_seconds and seconds >= settings.period_seconds)
            or (settings.period_iterations and iterations >= settings.period_iterations)
            or (
                pause is not None
                and iteration > self._last_iteration
                and self._last_answer is not None
                and now - self._last_answer >= pause
            )
            or (settings.first_iteration and iteration >= 1 and self._last_time is None)
        )
        kind: TriggerKind | None = "event" if self._waiting else None
        if kind is None and periodic:
            kind = "periodic"
        if kind is None:
            return None, []
        reported, self._waiting = self._waiting, []
        self.called(n_evaluations, iteration)
        return kind, reported

    def forced(
        self, n_evaluations: int, events: Sequence[Event], iteration: int = 0
    ) -> list[Event]:
        """Note a start or end call; return the events it reports."""
        reported = [*self._waiting, *self._new(events, n_evaluations)]
        self._waiting = []
        self.called(n_evaluations, iteration)
        return reported

    def _new(self, events: Sequence[Event], n_evaluations: int) -> list[Event]:
        """The events that appeared since the last check."""
        if not self.settings.events:
            return []
        active: set[str] = {event.kind for event in events}
        new = [
            event
            for event in events
            if event.kind not in self._active or event.kind == "failed_evaluations"
        ]
        self._active = active
        if any(event.kind == "failed_evaluations" for event in new):
            self.failures_since = n_evaluations
        return new
