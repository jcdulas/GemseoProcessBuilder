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

    launch_pause: float | None = 120.0
    """For an algorithm reporting its outer iterations: seconds since the
    start of the last call to Claude from which the end of the next outer
    iteration calls it again, whatever ``period_iterations``; ``None`` turns it
    off. A run that waits for Claude (see ``ClaudePilot``) is thus followed
    every 10 outer iterations or every 2 minutes, whichever comes first."""

    review_ceiling: float | None = 600.0
    """Once Claude has said in how many outer iterations it wants to be consulted
    again (``Decision.review_in``): the seconds after which it is consulted
    anyway, whatever it asked for; ``None`` turns it off."""

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
        self._review: int | None = None
        self._active: set[str] = set()
        self._waiting: list[Event] = []
        self.failures_since = 0
        """The first evaluation whose failures were not reported yet."""

    def called(self, n_evaluations: int, iteration: int = 0) -> None:
        """Note a call to Claude, whatever its trigger."""
        self._last_evaluation = n_evaluations
        self._last_iteration = iteration
        self._last_time = self._clock()

    def reset_iterations(self) -> None:
        """Count the outer iterations from 0 again: the run moved onto another state."""
        self._last_iteration = 0

    @property
    def review(self) -> int | None:
        """The outer iterations Claude asked to wait, if it did."""
        return self._review

    def set_review(self, iterations: int | None) -> None:
        """Wait this many outer iterations before the next periodic call.

        It replaces ``period_iterations`` and ``launch_pause`` (the seconds
        become the ceiling ``review_ceiling``); ``None`` gives them back.
        """
        self._review = iterations

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
        pause = settings.launch_pause
        every = settings.period_iterations
        if self._review is not None:
            # Claude chose its rhythm: its iterations, and a ceiling in seconds.
            every, pause = self._review, settings.review_ceiling
        periodic = bool(
            (settings.period and evaluations >= settings.period)
            or (settings.period_seconds and seconds >= settings.period_seconds)
            or (every and iterations >= every)
            or (
                pause is not None
                and iteration > self._last_iteration
                and (self._last_time is None or seconds >= pause)
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
