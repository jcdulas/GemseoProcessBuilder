"""The advisor: from a copy of the database to an answer of Claude (spec § 3, § 4.2).

The pilot prepares a :class:`Check` in the optimizer's thread (a snapshot of
the problem and a copy of the database entries, both cheap) and hands it to the
advisor. The advisor builds the history, runs the detectors and the triggers,
and, when a trigger fires, exchanges with Claude, in a background thread so
that the optimizer never waits. The pilot polls for the :class:`Advice`.

The run never depends on Claude (spec § 1.2): every failure is recorded, three
consecutive ones, or a refused authentication, turn the advisor off.
"""

import logging
import os
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from gemseo_claude_pilot.algorithms import AlgorithmInfo
from gemseo_claude_pilot.backends.base import EFFORTS
from gemseo_claude_pilot.backends.base import AuthenticationError
from gemseo_claude_pilot.backends.base import Backend
from gemseo_claude_pilot.backends.base import BackendUnavailableError
from gemseo_claude_pilot.backends.base import Effort
from gemseo_claude_pilot.backends.base import LoopingBackend
from gemseo_claude_pilot.backends.base import ToolSpec
from gemseo_claude_pilot.backends.base import Usage
from gemseo_claude_pilot.budget import Budget
from gemseo_claude_pilot.context import PastDecision
from gemseo_claude_pilot.context import TriggerKind
from gemseo_claude_pilot.context import build_context
from gemseo_claude_pilot.context import render
from gemseo_claude_pilot.critique import HEAVY_ACTIONS
from gemseo_claude_pilot.critique import review_request
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.design import DesignView
from gemseo_claude_pilot.detectors import DetectorSettings
from gemseo_claude_pilot.detectors import Event
from gemseo_claude_pilot.detectors import detect
from gemseo_claude_pilot.exchange import exchange
from gemseo_claude_pilot.guardrails import Checked
from gemseo_claude_pilot.guardrails import Limits
from gemseo_claude_pilot.guardrails import check
from gemseo_claude_pilot.journal import Journal
from gemseo_claude_pilot.privacy import Anonymizer
from gemseo_claude_pilot.privacy import DataLevel
from gemseo_claude_pilot.prompts import system_prompt
from gemseo_claude_pilot.snapshots import Entry
from gemseo_claude_pilot.snapshots import ProblemSnapshot
from gemseo_claude_pilot.snapshots import history_from_entries
from gemseo_claude_pilot.snapshots import iterate_entries
from gemseo_claude_pilot.tools import DESIGN_TOOLS
from gemseo_claude_pilot.tools import READ_TOOLS
from gemseo_claude_pilot.tools import SUBMIT_DECISION
from gemseo_claude_pilot.tools import ToolAnswers
from gemseo_claude_pilot.triggers import Triggers
from gemseo_claude_pilot.triggers import TriggerSettings

LOGGER = logging.getLogger(__name__)

MAX_FAILURES = 3
"""Consecutive failed calls after which the advisor turns itself off."""


@dataclass(frozen=True)
class Check:
    """What the advisor needs to look at the run, prepared by the pilot."""

    problem: ProblemSnapshot
    entries: list[Entry]
    pilot: Mapping[str, Any]
    """The mode, the allowed actions and the current segment, for Claude."""

    trigger: TriggerKind | None = None
    """A call to make whatever the triggers say (start, end), or ``None``."""

    question: str = ""
    """The question of the user, for the ``question`` trigger."""

    design: DesignView | None = None
    """The design, when the model describes its physics (spec § 4.8)."""


@dataclass(frozen=True)
class Advice:
    """What a call to Claude gave."""

    trigger: TriggerKind
    evaluation: int
    """The number of evaluations the call looked at."""

    text: str = ""
    checked: Checked | None = None
    events: tuple[Event, ...] = ()
    error: str = ""
    question: str = ""
    iteration: int = -1
    """The outer iteration the call looked at, for an algorithm reporting them."""

    @property
    def decision(self) -> Decision | None:
        """The decision that passed the checks, if any."""
        return None if self.checked is None else self.checked.decision


def _model(variable: str, default: str) -> str:
    return os.environ.get(variable) or default


DEFAULT_MODEL = "claude-opus-5-5"
"""The model of both roles by default: Claude Opus 5.5, at a low effort."""

DEFAULT_EFFORT = "low"

WITHOUT_EFFORT = frozenset({"claude-haiku-4-5"})
"""The models that take no effort."""


@dataclass
class Models:
    """The models of the two roles of spec § 5.4, and the effort of their calls.

    GEMSEO Process Builder passes the user's choice to the runner in
    ``GEMSEO_CLAUDE_PILOT_WATCH_MODEL``, ``GEMSEO_CLAUDE_PILOT_DECISION_MODEL`` and
    ``GEMSEO_CLAUDE_PILOT_EFFORT``.
    """

    watch: str = field(
        default_factory=lambda: _model("GEMSEO_CLAUDE_PILOT_WATCH_MODEL", DEFAULT_MODEL)
    )
    """For periodic calls."""

    decision: str = field(
        default_factory=lambda: _model(
            "GEMSEO_CLAUDE_PILOT_DECISION_MODEL", DEFAULT_MODEL
        )
    )
    """For events, the start, the end and questions."""

    effort: str = field(
        default_factory=lambda: _model("GEMSEO_CLAUDE_PILOT_EFFORT", DEFAULT_EFFORT)
    )
    """How much Claude thinks at each call: ``low`` answers in seconds to a
    minute, and a run is followed closely."""

    def effort_of(self, model: str) -> Effort:
        """The effort of a call to a model.

        None for a model that takes none, or for an effort not known.
        """
        if model in WITHOUT_EFFORT:
            return ""
        return next((effort for effort in EFFORTS if effort == self.effort), "")


@dataclass
class _State:
    result: Advice | None = None
    thread: threading.Thread | None = None
    failures: int = 0
    disabled: str = ""
    usage: Usage = field(default_factory=Usage)
    calls: int = 0
    budget_spent: str = ""


class Advisor:
    """Looks at the run on request and asks Claude when a trigger fires.

    Args:
        backend: The way to Claude.
        limits: The limits of the decisions.
        journal: Where the calls and answers are recorded.
        level: What may be sent.
        anonymizer: The anonymizer of the run, in ``anonymized``.
        triggers: When to call Claude.
        detectors: The thresholds of the detectors.
        models: The models to use.
        threaded: Whether calls run in a background thread; inline otherwise,
            which makes runs reproducible.
        algorithms: The algorithms of the driver's kind; GEMSEO's by default.
        budget: What the run may spend on Claude.
        review_heavy: Whether a decision that ends the run or changes its
            strategy is sent back to Claude for review, once, before it takes
            effect.
    """

    def __init__(
        self,
        backend: Backend | LoopingBackend,
        limits: Limits,
        journal: Journal,
        level: DataLevel = "no_code",
        anonymizer: Anonymizer | None = None,
        triggers: TriggerSettings | None = None,
        detectors: DetectorSettings | None = None,
        models: Models | None = None,
        threaded: bool = True,
        algorithms: Mapping[str, AlgorithmInfo] | None = None,
        budget: Budget | None = None,
        review_heavy: bool = True,
    ) -> None:
        self.review_heavy = review_heavy
        self.backend = backend
        self.budget = budget or Budget()
        self.limits = limits
        self.journal = journal
        self.level = level
        self.anonymizer = anonymizer
        self.triggers = Triggers(triggers or TriggerSettings())
        self.detectors = detectors or DetectorSettings()
        self.models = models or Models()
        self.threaded = threaded
        self.algorithms = algorithms
        self.decisions: list[PastDecision] = []
        self.latencies: list[float] = []
        """The seconds each exchange with Claude took, in order."""

        self._state = _State()
        self._lock = threading.Lock()

    @property
    def disabled(self) -> str:
        """Why the advisor is off, or nothing."""
        return self._state.disabled

    @property
    def busy(self) -> bool:
        """Whether a check is being made."""
        thread = self._state.thread
        return thread is not None and thread.is_alive()

    @property
    def usage(self) -> Usage:
        """The tokens spent so far."""
        return self._state.usage

    @property
    def calls(self) -> int:
        """The exchanges with Claude so far."""
        return self._state.calls

    @property
    def budget_spent(self) -> str:
        """Why the budget allows no more call, or nothing."""
        return self._state.budget_spent

    def submit(self, request: Check) -> bool:
        """Look at the run, in the background if threaded; ``False`` if busy or off."""
        if self.disabled or self.busy:
            return False
        if not self.threaded:
            self._store(self._look(request))
            return True
        thread = threading.Thread(
            target=lambda: self._store(self._look(request)),
            name="claude-pilot-advisor",
            daemon=True,
        )
        self._state.thread = thread
        thread.start()
        return True

    def poll(self) -> Advice | None:
        """The advice of the last check, once; ``None`` if none is ready."""
        with self._lock:
            result, self._state.result = self._state.result, None
        return result

    def wait(self, timeout: float | None = None) -> Advice | None:
        """Wait for the check in progress, then return its advice."""
        thread = self._state.thread
        if thread is not None:
            thread.join(timeout)
        return self.poll()

    def now(self, request: Check) -> Advice | None:
        """Look at the run and wait for the advice (start and end calls)."""
        self.wait()
        if not self.submit(request):
            return None
        return self.wait()

    def _store(self, advice: Advice | None) -> None:
        with self._lock:
            self._state.result = advice

    def _look(self, request: Check) -> Advice | None:
        """Build the history, check the triggers, and ask Claude if one fires."""
        try:
            return self._ask(request)
        except Exception as error:  # The run never depends on Claude.
            LOGGER.warning("The Claude pilot failed: %s", error)
            self._failed(error)
            return None

    def _ask(self, request: Check) -> Advice | None:
        problem = request.problem
        history = history_from_entries(request.entries, problem)
        n = history.n_evaluations
        reports = problem.algorithm_state
        # An algorithm reporting its outer iterations is read on its iterates:
        # its inner iterations are not its progress.
        iterates = (
            history_from_entries(iterate_entries(request.entries, reports), problem)
            if reports
            else None
        )
        # The detectors look for the symptoms of an optimization, not of a DOE.
        events = (
            []
            if problem.driver_kind == "doe"
            else detect(
                history,
                problem,
                self.detectors,
                since=self.triggers.failures_since,
                iterates=iterates,
            )
        )
        iteration = int(reports[-1]["iteration"]) if reports else -1
        trigger = request.trigger
        if trigger is None:
            trigger, reported = self.triggers.due(n, events, max(iteration, 0))
            if trigger is None:
                return None
        else:
            reported = self.triggers.forced(n, events, max(iteration, 0))
        if self._over_budget():
            return None
        design = request.design
        # The design itself at every call: Claude anticipates where it heads.
        detail = design is not None
        context = render(
            build_context(
                problem,
                history,
                trigger=trigger,
                events=reported,
                decisions=self.decisions,
                level=self.level,
                anonymizer=self.anonymizer,
                pilot=request.pilot,
                question=request.question,
                design=design,
                design_detail=detail,
            )
        )
        if detail:
            assert design is not None
            point = design.main_point()
            if point is not None:
                self.journal.write(
                    "design", trigger=trigger, evaluations=n, **design.detail(point)
                )
        model = self.models.watch if trigger == "periodic" else self.models.decision
        self.journal.write(
            "call",
            trigger=trigger,
            evaluation=n,
            backend=self.backend.name,
            model=model,
            context=context,
            question=request.question,
        )
        anonymizer = self.anonymizer if self.level == "anonymized" else None

        def check_decision(decision: Decision) -> Checked:
            if anonymizer is not None:
                decision = anonymizer.decision(decision)
            return check(
                decision,
                problem,
                self.limits,
                n,
                self.algorithms,
                design=design,
                restarts=int(request.pilot.get("restarts", 0)),
                comparisons=int(request.pilot.get("comparisons", 0)),
                explorations=request.pilot.get("explorations"),
            )

        def review(decision: Decision) -> str:
            if not self.review_heavy or decision.action.kind not in HEAVY_ACTIONS:
                return ""
            left = max(problem.evaluation_budget - n, 0)
            per_iteration = None
            if reports:
                per_iteration = max(
                    float(reports[-1].get("evaluation") or 0)
                    / max(int(reports[-1]["iteration"]), 1),
                    1.0,
                )
            return review_request(
                decision,
                left,
                None if per_iteration is None else int(left / per_iteration),
                request.pilot.get("track_record"),
            )

        self._state.calls += 1
        started = time.perf_counter()
        try:
            result = exchange(
                self.backend,
                system_prompt(),
                model,
                context,
                check_decision,
                answer_tool=ToolAnswers(
                    problem,
                    history,
                    request.entries,
                    self.level,
                    self.anonymizer,
                    self.algorithms,
                    design,
                ),
                # A report is text: Claude reads, and decides nothing.
                tools=_tools(trigger, design is not None),
                effort=self.models.effort_of(model),
                review=review,
            )
        except Exception as error:
            self.latencies.append(time.perf_counter() - started)
            self._failed(error)
            return Advice(
                trigger,
                n,
                events=tuple(reported),
                error=str(error),
                question=request.question,
                iteration=iteration,
            )
        self.latencies.append(time.perf_counter() - started)
        self._state.failures = 0
        self._state.usage += result.usage
        text = result.text if anonymizer is None else anonymizer.reveal(result.text)
        decision = None if result.checked is None else result.checked.decision
        self.journal.write(
            "answer",
            trigger=trigger,
            evaluation=n,
            text=text,
            decision=decision,
            notes=[] if result.checked is None else list(result.checked.notes),
            rejections=list(result.rejections),
            usage=result.usage,
            question=request.question,
        )
        if decision is not None:
            self.decisions.append(PastDecision(n, decision))
        return Advice(
            trigger,
            n,
            text,
            result.checked,
            tuple(reported),
            question=request.question,
            iteration=iteration,
        )

    def _over_budget(self) -> bool:
        """Whether the budget allows no more call; recorded the first time."""
        state = self._state
        if state.budget_spent:
            return True
        state.budget_spent = self.budget.spent(state.calls, state.usage)
        if state.budget_spent:
            LOGGER.info("The Claude pilot stops asking: %s.", state.budget_spent)
            self.journal.write("status", state="budget", reason=state.budget_spent)
        return bool(state.budget_spent)

    def _failed(self, error: Exception) -> None:
        """Record a failed call; turn the advisor off after too many."""
        state = self._state
        state.failures += 1
        self.journal.write(
            "status", state="error", error=f"{type(error).__name__}: {error}"
        )
        if isinstance(error, AuthenticationError):
            state.disabled = f"authentication failed: {error}"
        elif isinstance(error, BackendUnavailableError):
            state.disabled = str(error)
        elif state.failures >= MAX_FAILURES:
            state.disabled = (
                f"{state.failures} calls failed in a row; the last: {error}"
            )
        if state.disabled:
            LOGGER.warning("The Claude pilot is off for this run: %s", state.disabled)
            self.journal.write("status", state="disabled", reason=state.disabled)


def _tools(trigger: str, design: bool) -> tuple[ToolSpec, ...]:
    """The tools of a call.

    The design's when the model describes it; no decision for a report.
    """
    tools = (*READ_TOOLS, *(DESIGN_TOOLS if design else ()))
    return tools if trigger == "report" else (*tools, SUBMIT_DECISION)
