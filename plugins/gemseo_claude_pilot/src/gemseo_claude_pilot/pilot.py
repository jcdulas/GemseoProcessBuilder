"""The pilot: runs a scenario in segments, adjusted by Claude (spec § 4).

Example:
    >>> pilot = ClaudePilot(mode="pilot", backend=backend)
    >>> result = pilot.execute(scenario, algo_name="SLSQP", max_iter=200)

A segment is one ``scenario.execute`` with fixed settings. During a segment,
the pilot checks the triggers every few evaluations; Claude answers in the
background. A decision that passes the guardrails ends the segment at the next
iteration boundary; the next segment starts from the best point so far, with
the evaluations already made kept in the database: GEMSEO does not evaluate
them again. The run ends when a segment ends by itself and Claude asks for no
other, when Claude stops it, or when the evaluation budget is spent.

In Advisor mode, a decision is a proposal the user accepts or rejects in GEMSEO
Process Builder (spec § 4.1); the pilot talks to it through
:mod:`gemseo_claude_pilot.events`.

The algorithms of the large-scale optimizer (``LSO_MMA``, ``LSO_GCMMA``, package
``gemseo-lso``) report each outer iteration and take settings between two of
them: the pilot gives the reports to Claude, and applies a change of their
live settings, or a switch between them, at the next outer iteration without
ending the segment (spec § 4.4; spec § 8 of the large-scale optimizer).

A model whose design lies on a grid may describe its physics (spec § 4.8): the
pilot then gives Claude maps and physical indicators of the design, and lets
it restart the run from another design, a past one transformed on its grid.
"""

import logging
import math
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import is_dataclass
from dataclasses import replace
from pathlib import Path
from statistics import median
from typing import Any
from typing import Literal

import numpy as np

from gemseo_claude_pilot import events
from gemseo_claude_pilot.advisor import Advice
from gemseo_claude_pilot.advisor import Advisor
from gemseo_claude_pilot.advisor import Check
from gemseo_claude_pilot.advisor import Models
from gemseo_claude_pilot.algorithms import gemseo_algorithms
from gemseo_claude_pilot.backends import create_backend
from gemseo_claude_pilot.backends.base import Backend
from gemseo_claude_pilot.backends.base import LoopingBackend
from gemseo_claude_pilot.backends.base import Usage
from gemseo_claude_pilot.budget import Budget
from gemseo_claude_pilot.context import TriggerKind
from gemseo_claude_pilot.critique import verdict
from gemseo_claude_pilot.decisions import ActionKind
from gemseo_claude_pilot.decisions import AddSamples
from gemseo_claude_pilot.decisions import Adopt
from gemseo_claude_pilot.decisions import ChangeDesignSpace
from gemseo_claude_pilot.decisions import ChangeSettings
from gemseo_claude_pilot.decisions import ChangeSubScenario
from gemseo_claude_pilot.decisions import Compare
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.decisions import Explore
from gemseo_claude_pilot.decisions import ExploreStart
from gemseo_claude_pilot.decisions import Option
from gemseo_claude_pilot.decisions import Prediction
from gemseo_claude_pilot.decisions import Restart
from gemseo_claude_pilot.decisions import RestoreFeasibility
from gemseo_claude_pilot.decisions import Steer
from gemseo_claude_pilot.decisions import Stop
from gemseo_claude_pilot.decisions import SwitchAlgorithm
from gemseo_claude_pilot.decisions import VariableChange
from gemseo_claude_pilot.design import DesignSource
from gemseo_claude_pilot.design import RestartRecord
from gemseo_claude_pilot.detectors import DetectorSettings
from gemseo_claude_pilot.exploration import ExplorationSettings
from gemseo_claude_pilot.exploration import Explorer
from gemseo_claude_pilot.exploration import Job
from gemseo_claude_pilot.exploration import Outcome
from gemseo_claude_pilot.guardrails import ACTIONS_OF_DRIVER
from gemseo_claude_pilot.guardrails import Limits
from gemseo_claude_pilot.journal import Journal
from gemseo_claude_pilot.privacy import Anonymizer
from gemseo_claude_pilot.privacy import DataLevel
from gemseo_claude_pilot.progress import Progress
from gemseo_claude_pilot.progress import TrialSettings
from gemseo_claude_pilot.progress import harm
from gemseo_claude_pilot.progress import merit
from gemseo_claude_pilot.progress import progress
from gemseo_claude_pilot.progress import remaining_gain
from gemseo_claude_pilot.snapshots import DriverKind
from gemseo_claude_pilot.snapshots import ProblemSnapshot
from gemseo_claude_pilot.snapshots import components_of
from gemseo_claude_pilot.snapshots import database_entries
from gemseo_claude_pilot.snapshots import history_from_entries
from gemseo_claude_pilot.snapshots import snapshot_problem
from gemseo_claude_pilot.snapshots import sub_scenarios_of
from gemseo_claude_pilot.triggers import TriggerSettings

LOGGER = logging.getLogger(__name__)

PilotMode = Literal["observer", "advisor", "pilot"]

PILOT_MODES: tuple[PilotMode, ...] = ("observer", "advisor", "pilot")

FOLDER_VARIABLE = "GEMSEO_CLAUDE_PILOT_FOLDER"
"""The environment variable naming the folder of the journal (set by the runner)."""

DECISION_EXPIRY = 50
"""Evaluations after which a decision is too old to be applied (open point 5)."""

DECISION_EXPIRY_ITERATIONS = 10
"""Outer iterations after which a decision on an LSO algorithm is too old: its
evaluations are a poor clock (GCMMA makes several per iteration; in the first
piloted bracket, a restart expired after 77 evaluations but 26 iterations)."""

LSO_ALGORITHMS = {"LSO_MMA": "mma", "LSO_GCMMA": "gcmma"}
"""The algorithms of the large-scale optimizer, and their method."""

TRIAL = TrialSettings()
"""When a change of the live settings is judged harmful and undone."""

ALGORITHM_REPORTS = 200
"""The last reports of an algorithm kept in a snapshot."""

MAX_REVIEW = 25
"""The outer iterations Claude may let go by without being consulted."""

OVERHEAD_SHARE = 0.25
"""The share of the time of the run a consultation of Claude should not exceed:
the review period suggested to Claude keeps its calls below it."""

TIMING_WINDOW = 10
"""The last outer iterations the time of an iteration is measured over."""

STOP_GAIN = 0.005
"""A stop for convergence is refused while the objective is expected to gain
more than this share of itself over the iterations left."""

ANSWER_TIMEOUT = 120.0
"""Seconds the pilot waits for the user's answer to a proposal made at the end
of a segment, before ending the run."""


class _EndOfSegment(Exception):  # noqa: N818 - a signal, not an error
    """Raised in the new-iteration listener to end the segment cleanly."""


@dataclass
class Segment:
    """One ``scenario.execute`` of a piloted run."""

    index: int
    algo_name: str
    settings: dict[str, Any]
    first_evaluation: int
    reason: str
    """Why it started: the user's settings, or the decision of Claude."""

    last_evaluation: int = -1
    ended: str = ""
    """``completed`` when the algorithm stopped by itself, else ``decision``."""


@dataclass
class PilotResult:
    """What happened in a piloted run."""

    segments: list[Segment] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    """The decisions applied, in order."""

    diagnoses: list[str] = field(default_factory=list)
    """What Claude said at each call."""

    stop_reason: str = ""
    """``completed``, ``stopped by Claude``, ``stopped by the user``, ``budget
    spent`` or ``no backend``."""

    disabled: str = ""
    """Why the pilot turned itself off, if it did."""

    best_evaluation: int = -1
    usage: Usage = field(default_factory=Usage)
    report: str = ""
    """The analysis of the run written by Claude at its end, in Markdown."""


@dataclass
class _Trial:
    """A change of the live settings, judged on what follows it."""

    decision: Decision
    changes: dict[str, Any]
    """The settings it changed, with their new value."""

    previous: dict[str, Any]
    """The same settings, as they were."""

    method: str | None
    """The method it switched to, if it switched between MMA and GCMMA."""

    previous_method: str | None
    """The method before the switch."""

    iteration: int
    """The outer iteration it was applied after."""

    before: Progress | None
    """How the run progressed over the iterations before it; ``None`` when it had
    made too few to tell."""


@dataclass
class _Forecast:
    """A prediction of Claude, waiting for the iterations it is about."""

    decision: Decision
    prediction: Prediction
    before: float
    """The metric at the report the decision was made at."""

    due: int
    """The outer iteration the prediction is read at."""


@dataclass
class _Branch:
    """One branch of a comparison of strategies, run from the same state."""

    label: str
    algo_name: str
    settings: dict[str, Any]
    state: Path
    """Where its state is saved at its end."""

    first_report: int
    """Where its reports start in the reports of the run."""

    iterations: int
    count: int = 0
    done: bool = False
    merit: float = float("inf")
    reports: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _Proposal:
    """A decision waiting for the user's answer, in Advisor mode."""

    id: str
    decision: Decision
    evaluation: int
    iteration: int = -1


class ClaudePilot:
    """Runs an optimization scenario in segments, adjusted by Claude.

    Args:
        mode: ``observer`` (diagnoses only), ``advisor`` (proposals the user
            accepts in GEMSEO Process Builder; ``observer`` when nobody can
            answer, as in a plain script) or ``pilot`` (decisions applied).
        allowed_actions: The actions Claude may take; all by default.
        data_level: What may be sent to Claude (spec § 7).
        backend: The way to Claude, or its name: ``claude_code`` (the user's
            Claude Code and subscription), ``api_key`` or ``off``. By default
            the one named by ``GEMSEO_CLAUDE_PILOT_BACKEND``, else
            ``claude_code``. When it is off or cannot be used, the scenario
            runs as is.
        models: The models of the watch and decision roles.
        triggers: When to call Claude.
        detectors: The thresholds of the detectors.
        journal: The journal file; by default ``journal.jsonl`` in the folder
            named by ``GEMSEO_CLAUDE_PILOT_FOLDER``, else in ``<script>.pilot``
            next to the script; ``False`` keeps it in memory.
        threaded: Whether Claude answers in the background; inline otherwise,
            which makes runs reproducible but slower. By default, the large-scale
            optimizer (``LSO_MMA``, ``LSO_GCMMA``) waits for Claude at the end of
            an outer iteration, so that Claude has the time to think and to define
            a strategy that applies from the next iteration; any other algorithm
            goes on while Claude answers.
        budget: What one run may spend on Claude.
        answer_timeout: The seconds to wait for the user's answer to a
            proposal made when a segment ends by itself.
        report: Whether Claude writes an analysis of the run at its end
            (``report.md`` next to the journal); or a function called then,
            saying whether (to ask the user once the run is over).
        max_restarts: The restarts from another design allowed in a run,
            when the model describes the physics of its design.
        critical_review: Whether Claude must criticize its own analysis like an
            engineer: any action comes with an assessment (the hypotheses with the
            evidence for and against, where the analysis may be wrong, the
            alternatives, a measurable prediction), the pilot checks the
            predictions and tells Claude the record, and a decision that ends the
            run or changes its strategy is sent back for review once.
        exploration: What lets Claude explore other zones of the design space in
            other processes (``explore``, ``adopt``): a factory building a new
            scenario of the problem, and the limits of the explorations. Without
            it, the actions are not offered.
        adaptive_review: Whether Claude chooses when it is consulted again (the
            large-scale optimizer): the time of an iteration and of a call are
            given to it, and the number of iterations it asks for replaces the
            period of the triggers. Off, the triggers keep their period.
    """

    def __init__(
        self,
        mode: PilotMode = "advisor",
        allowed_actions: Sequence[ActionKind] | None = None,
        data_level: DataLevel = "no_code",
        backend: Backend | LoopingBackend | str | None = None,
        models: Models | None = None,
        triggers: TriggerSettings | None = None,
        detectors: DetectorSettings | None = None,
        journal: Path | str | Literal[False] | None = None,
        threaded: bool | None = None,
        budget: Budget | None = None,
        answer_timeout: float = ANSWER_TIMEOUT,
        report: bool | Callable[[], bool] = True,
        max_restarts: int = 3,
        adaptive_review: bool = True,
        critical_review: bool = True,
        exploration: ExplorationSettings | None = None,
    ) -> None:
        self.exploration = exploration
        self.critical_review = critical_review
        self.adaptive_review = adaptive_review
        self.mode: PilotMode = mode
        self.max_restarts = max_restarts
        self.allowed_actions = allowed_actions
        self.data_level = data_level
        if backend is None or isinstance(backend, str):
            backend = create_backend(backend)
        self.backend = backend
        self.budget = budget or Budget()
        self.models = models or Models()
        self.triggers = triggers or TriggerSettings()
        self.detectors = detectors or DetectorSettings()
        self.journal = Journal(_journal_path(journal))
        self.threaded = threaded
        self.answer_timeout = answer_timeout
        self.report = report

    def execute(self, scenario: Any, algo_name: str, **settings: Any) -> PilotResult:
        """Run the scenario with an algorithm and its settings.

        ``max_iter`` (``n_samples`` for a DOE) is the evaluation budget of
        the whole run: no segment goes beyond it.

        Args:
            scenario: A GEMSEO optimization or DOE scenario.
            algo_name: The algorithm of the first segment.
            **settings: Its settings.
        """
        return _Run(self, scenario, algo_name, dict(settings)).execute()


class _Run:
    """The state of one piloted execution."""

    def __init__(
        self,
        pilot: ClaudePilot,
        scenario: Any,
        algo_name: str,
        settings: dict[str, Any],
    ) -> None:
        self.pilot = pilot
        self.scenario = scenario
        self.problem = scenario.formulation.optimization_problem
        self.algo_name = algo_name
        self.settings = settings
        self.kind: DriverKind = (
            "doe" if type(scenario).__name__ == "DOEScenario" else "optimization"
        )
        self.budget = (
            int(settings.get("n_samples") or 0)
            if self.kind == "doe"
            else int(settings.get("max_iter") or _default_max_iter(algo_name))
        )
        self.result = PilotResult()
        self.reports: list[dict[str, Any]] = []
        """The reports of the outer iterations of an LSO algorithm."""
        self.live: Any = None
        """The live run of an LSO algorithm the pilot watches, while it runs."""
        self.original = self._snapshot()
        self.pending: Decision | None = None
        self.proposal: _Proposal | None = None
        self.proposals = 0
        self.active = False
        self.last_check = 0
        self.last_iteration = 0
        """The outer iteration of an LSO algorithm last checked."""
        self.stopped = False
        self.questions: list[str] = []
        """Questions of the user waiting for Claude."""
        self.user_algorithm = (algo_name, dict(settings))
        self.rest = "no"
        """For a DOE: the samples Claude left are drawn once, as the user asked."""
        self.region: list[VariableChange] = []
        """For a DOE: the sub-region the next segment samples."""
        mode = pilot.mode
        if mode == "advisor" and not events.connected():
            LOGGER.info(
                "The advisor mode needs GEMSEO Process Builder to accept the "
                "proposals: the Claude pilot only observes this run."
            )
            mode = "observer"
        self.mode: PilotMode = mode
        self.limits = self._limits()
        self.design = DesignSource.find(scenario, self.original)
        """The design, when a discipline describes its physics (spec § 4.8): sent
        to Claude whatever the data level."""
        self.restarts: list[RestartRecord] = []
        self.trial: _Trial | None = None
        """The last change of the live settings, not judged yet."""

        self.reverted: list[dict[str, Any]] = []
        """The changes of settings that made the run worse and were undone."""

        self.stopping = False
        """Claude asked a running LSO algorithm to stop, once feasible."""

        self.explorer = Explorer(pilot.exploration) if pilot.exploration else None
        self.explored: dict[str, Outcome] = {}
        """The explorations that ended, by label, until one is adopted."""

        self.whys: dict[str, str] = {}
        self.explorations_made = 0
        self.exploration_ready = False
        """The explorations have all ended: Claude is to be told."""

        self.forecasts: list[_Forecast] = []
        """The predictions of Claude not read yet."""

        self.record = {"made": 0, "confirmed": 0}
        """The predictions read so far, and how many held."""

        self.comparisons = 0
        self.branch: _Branch | None = None
        """The branch of a comparison running now."""

        self.checkpoint: Path | None = None
        """The state a comparison starts its branches from."""

        self.resume: Path | None = None
        """The state the next segment resumes from."""

        self.scratch: Path | None = None
        """A folder for the states of a comparison, removed at the end."""

    def execute(self) -> PilotResult:
        pilot = self.pilot
        journal = pilot.journal
        journal.write(
            "status",
            state="started",
            mode=self.mode,
            algo_name=self.algo_name,
            settings=self.settings,
            budget=self.budget,
            data_level=pilot.data_level,
        )
        unavailable = _unavailable(pilot.backend)
        if not self.budget:
            unavailable = "a DOE needs n_samples to be piloted"
        if pilot.backend is None or unavailable:
            reason = unavailable or "no backend"
            LOGGER.warning(
                "The Claude pilot is off (%s): the scenario runs as is.", reason
            )
            self.result.stop_reason = "no backend"
            self.result.disabled = reason
            journal.write("status", state="disabled", reason=reason)
            _publish("copilot.status", state="disabled", reason=reason)
            self.scenario.execute(algo_name=self.algo_name, **self.settings)
            return self.result
        anonymizer = None
        if pilot.data_level == "anonymized":
            anonymizer = Anonymizer(self.original)
        self.advisor = Advisor(
            pilot.backend,
            self.limits,
            journal,
            pilot.data_level,
            anonymizer,
            pilot.triggers,
            pilot.detectors,
            pilot.models,
            self.algo_name not in LSO_ALGORITHMS
            if pilot.threaded is None
            else pilot.threaded,
            budget=pilot.budget,
            review_heavy=pilot.critical_review,
        )
        _publish("copilot.status", state="watching", mode=self.mode)
        self.problem.database.add_new_iter_listener(self._on_new_point)
        self._watch_runs()
        try:
            self._segments()
        except BaseException as error:
            journal.write("status", state="interrupted", error=type(error).__name__)
            _publish("copilot.status", state="off", reason="interrupted")
            raise
        finally:
            self.active = False
            self._forget_runs()
            if self.explorer is not None:
                self.explorer.stop()
            if self.scratch is not None:
                shutil.rmtree(self.scratch, ignore_errors=True)
        self._finish()
        return self.result

    def _segments(self) -> None:
        if self.pilot.triggers.start:
            self._handle(self._ask_now("start"))
        index = 0
        while True:
            self._take_commands()
            self._answer_questions()
            decision, self.pending = self.pending, None
            if self.stopped:
                self.result.stop_reason = "stopped by the user"
                return
            if isinstance(decision.action if decision else None, Stop):
                self.result.stop_reason = "stopped by Claude"
                return
            n = len(self.problem.database)
            remaining = self.budget - n
            if remaining <= 0:
                self.result.stop_reason = "budget spent"
                return
            if index > 0 and self.kind == "optimization":
                self._warm_start()
            reason = "the user's settings"
            if decision is not None:
                reason = self._apply(decision)
                # A comparison spent evaluations and may have been stopped.
                n = len(self.problem.database)
                remaining = self.budget - n
                if self.stopped:
                    self.result.stop_reason = "stopped by the user"
                    return
                if remaining <= 0:
                    self.result.stop_reason = "budget spent"
                    return
            elif self.rest == "due":
                self.algo_name, self.settings = (
                    self.user_algorithm[0],
                    dict(self.user_algorithm[1]),
                )
                self.rest = "done"
                reason = "the samples left, drawn as the user asked"
            segment = Segment(
                len(self.result.segments),
                self.algo_name,
                self._segment_settings(index, remaining),
                n,
                reason,
            )
            self.result.segments.append(segment)
            self.pilot.journal.write("segment", **asdict(segment))
            _publish("copilot.segment", **asdict(segment))
            LOGGER.info(
                "Claude pilot, segment %d: %s from evaluation %d (%s).",
                index,
                self.algo_name,
                n,
                reason,
            )
            self.active = True
            self.last_check = n
            algo_name, settings = self._execution(segment)
            self._reset_hooks()
            try:
                self.scenario.execute(algo_name=algo_name, **settings)
                segment.ended = "completed"
            except _EndOfSegment:
                segment.ended = "decision"
            self.active = False
            segment.last_evaluation = len(self.problem.database) - 1
            self.region = []  # A region holds for its segment only.
            index += 1
            if self.stopping:
                self.result.stop_reason = "stopped by Claude"
                return
            if segment.ended == "completed" and not self._continue():
                self.result.stop_reason = "completed"
                return

    def _continue(self) -> bool:
        """After a segment that ended by itself: whether Claude asks for another."""
        self._handle(self.advisor.wait())
        if len(self.problem.database) >= self.budget:
            return False  # No other segment can run.
        if self.pending is None and self.proposal is None and self.pilot.triggers.end:
            self._handle(self._ask_now("end"))
        if self.proposal is not None and self.pending is None:
            self._wait_for_answer()
        if self.pending is None and self.kind == "doe" and self.rest == "no":
            self.rest = "due"
        return self.pending is not None or self.stopped or self.rest == "due"

    def _wait_for_answer(self) -> None:
        """Wait for the user's answer to the open proposal, for a while."""
        _publish("copilot.status", state="waiting", proposal=self.proposal_id)
        deadline = time.monotonic() + self.pilot.answer_timeout
        while self.proposal is not None and time.monotonic() < deadline:
            self._take_commands()
            self._answer_questions()
            if self.stopped:
                return
            time.sleep(0.1)
        if self.proposal is not None:
            self._close_proposal("unanswered")
        _publish("copilot.status", state="watching", mode=self.mode)

    def _on_new_point(self, x: Any) -> None:
        """Called by GEMSEO when a new point starts: the iteration boundary."""
        if not self.active:
            return
        self._watch_live()
        self._take_commands()
        branch = self.branch
        if branch is not None:
            # A branch of a comparison runs its iterations and nothing else.
            if branch.done or self.stopped:
                raise _EndOfSegment
            return
        self._handle(self.advisor.poll())
        self._apply_now()
        if self._ends_segment():
            raise _EndOfSegment
        done = len(self.problem.database) - 1  # The new point is not evaluated yet.
        if self.questions and self.advisor.submit(
            self._check("question", done, self.questions[0])
        ):
            self.questions.pop(0)
            self._handle(self.advisor.poll())  # Inline advisors answer at once.
            self._apply_now()
            if self._ends_segment():
                raise _EndOfSegment
            return
        # An LSO algorithm is checked at each of its outer iterations.
        iteration = int(self.reports[-1]["iteration"]) if self.reports else 0
        new_iteration = iteration != self.last_iteration
        if new_iteration or done - self.last_check >= self.pilot.triggers.check_every:
            if self.advisor.submit(self._check(None, done)):
                self.last_check = done
                self.last_iteration = iteration
            self._handle(self.advisor.poll())  # Inline advisors answer at once.
            self._apply_now()
            if self._ends_segment():
                raise _EndOfSegment

    def _ends_segment(self) -> bool:
        """Whether the segment must end now: a decision, or the user's stop.

        More samples for a DOE wait for the sampling in progress to end.
        """
        if self.stopped:
            return True
        if self.pending is None:
            return False
        if isinstance(self.pending.action, Compare):
            # The branches start from a state the optimizer saves between two
            # of its iterations: the segment ends once it is there.
            return self.checkpoint is not None and self.checkpoint.is_file()
        return not isinstance(self.pending.action, AddSamples)

    def _apply_now(self) -> None:
        """Apply at once what needs no new segment.

        A change of a sub-optimization; a change of the live settings of an LSO
        algorithm, or a switch between its two methods.
        """
        decision = self.pending
        if decision is None:
            return
        if isinstance(decision.action, ChangeSubScenario):
            self.pending = None
            self._apply(decision)
        elif isinstance(decision.action, Explore):
            self.pending = None
            self._explore(decision, decision.action)
        elif isinstance(decision.action, Compare):
            self._save_checkpoint()
        elif self._apply_live(decision):
            self.pending = None

    def _reset_hooks(self) -> None:
        """Give GEMSEO a problem as it leaves one it ran to the end.

        A segment ended by an exception of the pilot skips GEMSEO's clean-up: the
        functions keep a callback of the library that ran it, and the next
        execution neither replaces it nor finds its own counter in a valid state
        (``'NoneType' object has no attribute 'evaluation_counter'``, once a
        library that ended is behind the callback).
        """
        for function in self.problem.functions:
            function.pre_compute_at_new_point = None
        self.problem.evaluation_counter.enabled = False

    def _watch_runs(self) -> None:
        """Follow every live run of an LSO algorithm on the problem, from its start."""
        try:
            from gemseo_lso.gemseo.live import on_open
        except ImportError:  # No large-scale optimizer: nothing to follow.
            return
        on_open(self.problem, self._follow)

    def _forget_runs(self) -> None:
        try:
            from gemseo_lso.gemseo.live import forget
        except ImportError:
            return
        forget(self.problem)

    def _follow(self, run: Any) -> None:
        """Follow the outer iterations of a live run, once."""
        if run is not self.live:
            self.live = run
            run.watch(self._on_report)

    def _watch_live(self) -> None:
        """Follow the outer iterations of an LSO algorithm, once it runs."""
        if self.algo_name not in LSO_ALGORITHMS:
            return
        try:
            from gemseo_lso.gemseo.live import live_run
        except ImportError:  # The algorithm runs, so its package is there.
            return
        run = live_run(self.problem)
        if run is not None:
            self._follow(run)

    def _on_report(self, report: Any) -> None:
        """Record the report of an outer iteration; the application charts it."""
        data = _report_data(report)
        data["evaluation"] = len(self.problem.database)
        branch = self.branch
        if branch is not None:
            data["branch"] = branch.label
        self.reports.append(data)
        self.pilot.journal.write("algorithm", **data)
        _publish("copilot.algorithm", **data)
        if branch is not None:
            branch.count += 1
            branch.done = branch.count >= branch.iterations
            return
        self._poll_explorations()
        self._read_forecasts()
        self._judge_trial()
        if self.active and not self.advisor.threaded:
            self._wait_for_claude(int(data["iteration"]))

    def _judge_trial(self) -> None:
        """Judge the last change of settings once enough iterations followed it.

        A change after which the run gained at least twice less per iteration,
        with no gain in feasibility nor in the KKT residual, is undone; Claude
        is told, and the same change is not accepted again.
        """
        trial = self.trial
        if trial is None or self.live is None:
            return
        window = TRIAL.window
        after = [r for r in self.reports if int(r["iteration"]) > trial.iteration]
        if len(after) < window:
            return
        self.trial = None
        measured = progress(after[:window])
        assert measured is not None
        reason = "" if trial.before is None else harm(trial.before, measured, TRIAL)
        if not reason:
            compared = (
                "too few iterations before it to compare"
                if trial.before is None
                else f"it gained {trial.before.gain:.2%} before"
            )
            self._note_outcome(
                trial.decision,
                f"Kept: over the {window} outer iterations that followed, the "
                f"objective gained {measured.gain:.2%} per iteration ({compared}).",
            )
            return
        try:
            if trial.previous:
                self.live.change(trial.previous)
            if trial.previous_method is not None:
                self.live.switch(trial.previous_method)
        except ValueError as error:
            LOGGER.warning("The change cannot be undone: %s", error)
            return
        self.settings.update(trial.previous)
        if trial.previous_method is not None:
            self.algo_name = _algorithm_of(trial.previous_method)
        self.reverted.append({"changes": trial.changes, "method": trial.method})
        text = (
            f"Undone after {window} outer iterations: {reason}. The same change "
            "is not accepted again."
        )
        self._note_outcome(trial.decision, text)
        self.pilot.journal.write(
            "rollback",
            decision=trial.decision,
            reason=reason,
            iteration=int(after[-1]["iteration"]),
        )
        LOGGER.info("Claude pilot: %s", text)
        _publish(
            "copilot.message",
            kind="diagnosis",
            text=text,
            trigger="rollback",
            evaluation=len(self.problem.database),
        )

    def _note_outcome(self, decision: Decision, text: str) -> None:
        """Tell Claude what became of a decision, at its next call."""
        decisions = self.advisor.decisions
        for index, item in enumerate(decisions):
            if item.decision is decision:
                decisions[index] = replace(
                    item, outcome=" ".join(filter(None, [item.outcome, text]))
                )
                return

    def _stop_refusal(self, decision: Decision) -> str:
        """Why a stop for convergence is refused now, or nothing.

        While the objective still falls, or after a change of settings not
        judged yet, a plateau may be the change's own doing.
        """
        action = decision.action
        if not isinstance(action, Stop) or action.reason != "converged":
            return ""
        if not self.reports:
            return ""
        if self.trial is not None:
            return (
                f"the change of settings made after iteration "
                f"{self.trial.iteration} is not judged yet; its verdict comes "
                f"after {TRIAL.window} iterations"
            )
        last = self.reports[-1]
        per_iteration = max(
            float(last.get("evaluation") or 0) / max(int(last["iteration"]), 1), 1.0
        )
        left = int(max(self.budget - len(self.problem.database), 0) / per_iteration)
        estimate = remaining_gain(self.reports, left)
        if estimate is not None and estimate.expected >= STOP_GAIN:
            return (
                f"the objective is still expected to gain {estimate.expected:.2%} "
                f"over the {left} iterations left (it gains "
                f"{estimate.per_iteration:.3%} per iteration now)"
            )
        return ""

    def _scratch_folder(self) -> Path:
        """A folder for the states of a comparison, removed at the end of the run."""
        if self.scratch is None:
            self.scratch = Path(tempfile.mkdtemp(prefix="claude_pilot_"))
        return self.scratch

    def _save_checkpoint(self) -> None:
        """Ask the optimizer to save its state after its current iteration."""
        if self.checkpoint is not None or self.live is None:
            return
        self.checkpoint = self._scratch_folder() / "checkpoint.h5"
        self.live.save(self.checkpoint)

    def _compare(self, decision: Decision, action: Compare) -> None:
        """Run the branches of a comparison from one state, and keep the best.

        Each branch, the current strategy first as the reference, is a segment
        resuming the saved state for a few outer iterations. The best end, by
        :func:`merit`, goes on: its state is resumed by the next segment, its
        reports are kept, the others are dropped from the reports of the run
        (their evaluations stay in the database and spend the budget).
        """
        checkpoint, self.checkpoint = self.checkpoint, None
        if checkpoint is None or not checkpoint.is_file() or not self.reports:
            self._note_outcome(
                decision, "Not run: the optimizer could not save its state."
            )
            return
        self.comparisons += 1
        self.trial = None
        first = len(self.reports)
        start = float(self.reports[-1]["objective"])
        branches = []
        for index, option in enumerate(
            [Option(label="current strategy"), *action.options]
        ):
            branch = self._run_branch(index, option, checkpoint, action.iterations)
            if branch is not None:
                branches.append(branch)
            if self.stopped:
                break
        self.branch = None
        if not branches:
            self._note_outcome(decision, "Not run: no evaluation left.")
            return
        for branch in branches:
            branch.merit = (
                merit(branch.reports, start) if branch.reports else float("inf")
            )
        best = min(branches, key=lambda branch: branch.merit)
        self.reports = [*self.reports[:first], *best.reports]
        self.resume = best.state if best.state.is_file() else checkpoint
        self.algo_name = best.algo_name
        self.settings = dict(best.settings)
        if best.reports:
            self.last_iteration = int(best.reports[-1]["iteration"])
        summary = ", ".join(
            f"{branch.label}: {branch.merit:+.3g}" for branch in branches
        )
        text = (
            f"Compared {len(branches)} strategies over {action.iterations} outer "
            f"iterations each from the same state; kept {best.label}. Merit "
            f"(relative change of the objective plus violation, lower is "
            f"better): {summary}."
        )
        self._note_outcome(decision, text)
        self.pilot.journal.write(
            "comparison",
            kept=best.label,
            start_objective=start,
            branches=[
                {
                    "label": branch.label,
                    "algo_name": branch.algo_name,
                    "merit": branch.merit,
                    "iterations": len(branch.reports),
                    "objective": branch.reports[-1]["objective"]
                    if branch.reports
                    else None,
                    "max_constraint": branch.reports[-1]["max_constraint"]
                    if branch.reports
                    else None,
                }
                for branch in branches
            ],
        )
        LOGGER.info("Claude pilot: %s", text)
        _publish(
            "copilot.message",
            kind="diagnosis",
            text=text,
            trigger="compare",
            evaluation=len(self.problem.database),
        )

    def _run_branch(
        self, index: int, option: Option, checkpoint: Path, iterations: int
    ) -> _Branch | None:
        """One branch of a comparison: a segment resuming the saved state."""
        n = len(self.problem.database)
        remaining = self.budget - n
        if remaining <= 0:
            return None
        algo_name = option.algo_name or self.algo_name
        settings = {**self.settings, **option.settings}
        state = self._scratch_folder() / f"branch_{index}.h5"
        branch = _Branch(
            option.label, algo_name, settings, state, len(self.reports), iterations
        )
        segment = Segment(
            len(self.result.segments),
            algo_name,
            {
                **settings,
                "max_iter": remaining,
                "resume_from": str(checkpoint),
                "save_state": str(state),
            },
            n,
            f"a branch of a comparison: {option.label}",
        )
        self.result.segments.append(segment)
        self.pilot.journal.write("segment", **asdict(segment))
        _publish("copilot.segment", **asdict(segment))
        self.branch = branch
        self.active = True
        self._reset_hooks()
        try:
            self.scenario.execute(algo_name=algo_name, **segment.settings)
            segment.ended = "completed"
        except _EndOfSegment:
            segment.ended = "decision"
        finally:
            self.active = False
        segment.last_evaluation = len(self.problem.database) - 1
        branch.reports = self.reports[branch.first_report :]
        return branch

    def _wait_for_claude(self, iteration: int) -> None:
        """At the end of an outer iteration, wait for Claude if a trigger fires.

        The optimizer does not go on while Claude thinks. What Claude decides
        applies from the next outer iteration: a change of the live settings, a
        switch or a steering is taken by the optimizer before it starts, and any
        other decision ends the segment at the first evaluation of the next one.
        """
        self._take_commands()
        trigger: TriggerKind | None = None
        if self.exploration_ready and self.explorer and not self.explorer.active:
            trigger = "exploration"  # They have all ended: Claude reads the results.
        if self.advisor.submit(self._check(trigger)):
            self.last_check = len(self.problem.database)
            self.last_iteration = iteration
            if trigger is not None:
                self.exploration_ready = False
        self._handle(self.advisor.poll())
        self._apply_now()

    def _apply_live(self, decision: Decision) -> bool:
        """Apply a decision to the running LSO algorithm, if it can take it.

        Returns:
            Whether the decision was handled here: applied, or refused by the
            algorithm (then recorded and dropped).
        """
        from_live = self._live_module()
        if from_live is None or from_live.live_run(self.problem) is not self.live:
            return False
        action = decision.action
        if isinstance(action, Steer):
            x = self._steered(action)
            self.live.move(x)
            self.result.decisions.append(decision)
            self.pilot.journal.write("decision", decision=decision, live=True)
            LOGGER.info("Claude pilot: the design steered (%s).", action.toward)
            return True
        if isinstance(action, Stop):
            # The optimizer brings its iterate back within the constraints,
            # then ends: it would otherwise end on its last, slightly infeasible,
            # iterate.
            self.live.stop(f"stopped by Claude: {action.reason}", when_feasible=True)
            self.stopping = True
            self.result.decisions.append(decision)
            self.pilot.journal.write("decision", decision=decision, live=True)
            LOGGER.info("Claude pilot: the run stops once feasible.")
            return True
        if isinstance(action, RestoreFeasibility):
            self.live.restore_feasibility()
            self.result.decisions.append(decision)
            self.pilot.journal.write("decision", decision=decision, live=True)
            LOGGER.info("Claude pilot: feasibility restored from the next iteration.")
            return True
        method = None
        if isinstance(action, ChangeSettings):
            changes = dict(action.settings)
        elif (
            isinstance(action, SwitchAlgorithm)
            and action.algo_name in LSO_ALGORITHMS
            and self.algo_name in LSO_ALGORITHMS
        ):
            # The guardrails give the switch the evaluations left: the running
            # execution keeps its own budget.
            changes = {
                name: value
                for name, value in action.settings.items()
                if name != "max_iter"
            }
            method = LSO_ALGORITHMS[action.algo_name]
        else:
            return False
        if set(changes) - from_live.LIVE_SETTINGS:
            return False  # A new segment applies it.
        if self.trial is not None:
            reason = (
                f"the change made after iteration {self.trial.iteration} is not "
                f"judged yet (its verdict comes after {TRIAL.window} iterations): "
                "one change at a time"
            )
            self._note_outcome(decision, f"Refused: {reason}.")
            self.pilot.journal.write("status", state="refused", reason=reason)
            return True
        if {"changes": changes, "method": method} in self.reverted:
            reason = "this change was undone: it made the run worse"
            self._note_outcome(decision, f"Refused: {reason}.")
            self.pilot.journal.write("status", state="refused", reason=reason)
            return True
        previous = {name: self.live.settings.get(name) for name in changes}
        previous_method = str(self.reports[-1]["method"]) if self.reports else None
        before = progress(self.reports[-TRIAL.window :])
        try:
            if changes:
                self.live.change(changes)
            if method is not None:
                self.live.switch(method)
        except ValueError as error:
            self.pilot.journal.write("status", state="refused", reason=str(error))
            LOGGER.warning("The Claude pilot's decision is refused: %s", error)
            return True
        if len(self.reports) < TRIAL.window:
            before = None
        self.trial = _Trial(
            decision,
            changes,
            previous,
            method,
            previous_method if method is not None else None,
            int(self.reports[-1]["iteration"]) if self.reports else 0,
            before,
        )
        self.settings.update(changes)
        if isinstance(action, SwitchAlgorithm):
            self.algo_name = action.algo_name
        self.result.decisions.append(decision)
        self.pilot.journal.write("decision", decision=decision, live=True)
        return True

    def _live_module(self) -> Any:
        """The module of the live runs of the large-scale optimizer, if running."""
        if self.live is None:
            return None
        from gemseo_lso.gemseo import live

        return live

    def _segment_settings(self, index: int, remaining: int) -> dict[str, Any]:
        """The settings of a segment, within the evaluations left.

        A DOE sampling again with the same method gets another seed, or it
        would draw the same points again.
        """
        if self.kind == "optimization":
            max_iter = min(int(self.settings.get("max_iter") or remaining), remaining)
            return {**self.settings, "max_iter": max_iter}
        n_samples = min(int(self.settings.get("n_samples") or remaining), remaining)
        fields = gemseo_algorithms("doe")[self.algo_name].settings_model.model_fields
        # Claude places the other half; a method without a seed would draw the
        # same points again for the rest, so it keeps them all.
        allowed = self.limits.allowed_actions
        if index == 0 and "add_samples" in allowed and "seed" in fields:
            n_samples = (n_samples + 1) // 2
        settings = {**self.settings, "n_samples": n_samples}
        if index > 0 and "seed" in fields and "seed" not in self.settings:
            settings["seed"] = index + 1
        return settings

    def _execution(self, segment: Segment) -> tuple[str, dict[str, Any]]:
        """The algorithm and settings a segment runs with.

        A DOE sampling a sub-region draws its points in a copy of the design
        space narrowed to the region, then evaluates them with ``CustomDOE``:
        the bounds of the problem never change, so GEMSEO can set its best point
        at the end of the segment wherever it is.
        """
        if self.resume is not None:
            # After a comparison: the state of the branch kept goes on.
            segment.settings = {**segment.settings, "resume_from": str(self.resume)}
            self.resume = None
        if not self.region:
            return segment.algo_name, segment.settings
        from gemseo import compute_doe

        space = deepcopy(self.problem.design_space)
        for change in self.region:
            size = space.get_size(change.name)
            if change.lower is not None:
                space.set_lower_bound(
                    change.name, np.broadcast_to(change.lower, size).astype(float)
                )
            if change.upper is not None:
                space.set_upper_bound(
                    change.name, np.broadcast_to(change.upper, size).astype(float)
                )
        samples = compute_doe(space, algo_name=segment.algo_name, **segment.settings)
        return "CustomDOE", {"samples": samples}

    def _answer_questions(self) -> None:
        """Answer the questions of the user now (between two segments)."""
        while self.questions and not self.advisor.disabled:
            self._handle(self._ask_now("question", self.questions.pop(0)))

    def _ask_now(self, trigger: TriggerKind, question: str = "") -> Advice | None:
        _publish("copilot.status", state="thinking", trigger=trigger)
        advice = self.advisor.now(self._check(trigger, question=question))
        _publish("copilot.status", state="watching", mode=self.mode)
        return advice

    def _handle(self, advice: Advice | None) -> None:
        """Record what Claude said; keep a decision, or propose it."""
        if advice is None:
            if self.advisor.disabled and not self.result.disabled:
                self.result.disabled = self.advisor.disabled
                _publish(
                    "copilot.status", state="disabled", reason=self.result.disabled
                )
            return
        self._publish_usage()
        if advice.trigger == "report":
            self._report(advice.text)
            return
        decision = advice.decision
        text = decision.diagnosis if decision is not None else advice.text
        if advice.trigger == "question":
            text = advice.text or text  # The answer in words, then any decision.
        if text:
            self.result.diagnoses.append(text)
            LOGGER.info("Claude (%s): %s", advice.trigger, text)
        if decision is not None and decision.review_in:
            self._set_review(decision.review_in)
        if decision is not None:
            self._forecast(decision)
        acting = decision is not None and decision.action.kind != "none"
        answering = advice.trigger == "question"
        if text and (answering or not acting or self.mode == "observer"):
            kind = "diagnosis" if decision is not None and not answering else "answer"
            _publish(
                "copilot.message",
                kind=kind,
                text=text,
                trigger=advice.trigger,
                evaluation=advice.evaluation,
                question=advice.question,
            )
        if not acting or self.mode == "observer":
            return
        assert decision is not None
        refusal = self._stop_refusal(decision)
        if refusal:
            LOGGER.info("Claude pilot: the stop is refused: %s.", refusal)
            self._note_outcome(
                decision, f"Refused: {refusal}. The run goes on; ask again later."
            )
            self.pilot.journal.write("status", state="refused", reason=refusal)
            return
        age, expired = self._age(advice.evaluation, advice.iteration)
        if expired:
            self.pilot.journal.write(
                "status", state="expired", evaluation=advice.evaluation, age=age
            )
            return
        if self.mode == "pilot":
            self.pending = decision
            _publish(
                "copilot.message",
                kind="decision",
                text=decision.diagnosis,
                decision=decision.model_dump(mode="json"),
                evaluation=advice.evaluation,
            )
            return
        if self.proposal is not None:
            self._close_proposal("replaced")
        self.proposals += 1
        self.proposal = _Proposal(
            f"p{self.proposals}", decision, advice.evaluation, advice.iteration
        )
        self.pilot.journal.write(
            "proposal",
            id=self.proposal.id,
            decision=decision,
            evaluation=advice.evaluation,
        )
        _publish(
            "copilot.message",
            kind="proposal",
            id=self.proposal.id,
            text=decision.diagnosis,
            decision=decision.model_dump(mode="json"),
            evaluation=advice.evaluation,
        )

    def _start_design(self, start: ExploreStart) -> Any:
        """The design an exploration starts from: a design of the run, moved."""
        entries = database_entries(self.problem)
        space = self.problem.design_space
        if not entries:
            return space.get_current_value()
        iterates = self._iterates(len(entries))
        history = history_from_entries(entries, self._snapshot())
        base = start.base
        if base == "best" and history.best_index >= 0:
            index = history.best_index
        elif isinstance(base, int) and 0 <= base < len(entries):
            index = base
        else:
            index = iterates[-1]
        x = np.array(entries[index][0], dtype=float)
        anticipate = start.anticipate if base == "current" else None
        x = self._compose(
            x, entries, iterates, anticipate, start.transforms, start.variables
        )
        if start.perturb is not None:
            lower, upper = space.get_lower_bounds(), space.get_upper_bounds()
            noise = np.random.default_rng(start.perturb.seed).standard_normal(x.size)
            x = np.clip(x + start.perturb.scale * (upper - lower) * noise, lower, upper)
        return x

    def _explore(self, decision: Decision, action: Explore) -> None:
        """Start the explorations of a decision, in processes of their own.

        They run the user's algorithm and settings from their starting design, no
        Claude, while the main run goes on; Claude is consulted when they have
        all ended.
        """
        settings, explorer = self.pilot.exploration, self.explorer
        if settings is None or explorer is None:
            return
        algo_name, algo_settings = self.user_algorithm
        scratch = self._scratch_folder()
        jobs = []
        for index, start in enumerate(action.starts):
            x0 = self._start_design(start)
            self.whys[start.label] = start.why
            jobs.append(
                Job(
                    label=start.label,
                    factory=settings.factory,
                    algo_name=algo_name,
                    settings=dict(algo_settings),
                    x0=[float(value) for value in x0],
                    iterations=min(action.iterations, settings.max_iterations),
                    state_path=str(
                        scratch / f"exploration_{self.explorations_made}_{index}.h5"
                    ),
                )
            )
        explorer.start(jobs)
        self.explorations_made += 1
        self.exploration_ready = False
        self.pilot.journal.write(
            "exploration",
            starts=[{"label": s.label, "why": s.why} for s in action.starts],
            iterations=action.iterations,
        )
        self.result.decisions.append(decision)
        self.pilot.journal.write("decision", decision=decision, live=True)
        LOGGER.info(
            "Claude pilot: %d explorations started (%s).",
            len(jobs),
            ", ".join(job.label for job in jobs),
        )

    def _poll_explorations(self) -> None:
        """Collect the explorations that have ended; Claude reads them at the end."""
        if self.explorer is None:
            return
        for outcome in self.explorer.poll():
            outcome.why = self.whys.get(outcome.label, "")
            self.explored[outcome.label] = outcome
            data = {k: v for k, v in asdict(outcome).items() if k != "best_x"}
            self.pilot.journal.write("exploration_result", **data)
            self.exploration_ready = True

    def _adopt(self, action: Adopt) -> None:
        """Move the main run onto an exploration: its best design and its state.

        The next segment resumes the optimizer state the exploration saved; the
        reports of the run start again, they were those of another path.
        """
        outcome = self.explored.get(action.exploration)
        if outcome is None:
            return
        space = self.problem.design_space
        if outcome.best_x is not None:
            space.set_current_value(
                np.clip(
                    np.asarray(outcome.best_x, dtype=float),
                    space.get_lower_bounds(),
                    space.get_upper_bounds(),
                )
            )
        state = Path(outcome.state_path)
        self.resume = state if state.is_file() else None
        self.reports = []
        self.last_iteration = 0
        self.forecasts = []
        self.trial = None
        self.advisor.triggers.reset_iterations()
        self.explored.clear()
        self.pilot.journal.write(
            "adoption", exploration=action.exploration, objective=outcome.best_objective
        )
        LOGGER.info("Claude pilot: the main run moves onto %s.", action.exploration)

    def _exploration_context(self) -> dict[str, Any]:
        """Where the explorations stand, and what the ended ones reached.

        Their results are set against the main run: its best feasible objective,
        where its iterate is and how fast it still progresses.
        """
        explorer = self.explorer
        assert explorer is not None
        history = history_from_entries(database_entries(self.problem), self._snapshot())
        main: dict[str, Any] = {}
        main_best = None
        if history.best_index >= 0:
            main_best = float(history.objective[history.best_index])
            main["best_feasible_objective"] = main_best
        if self.reports:
            last = self.reports[-1]
            main["current_objective"] = float(last["objective"])
            main["current_violation"] = float(last["max_constraint"])
            measured = progress(self.reports[-TIMING_WINDOW:])
            if measured is not None:
                main["gain_per_iteration"] = measured.gain
        results = []
        for label, outcome in self.explored.items():
            item = {
                key: value
                for key, value in asdict(outcome).items()
                if key not in ("best_x", "state_path", "label")
                and value not in (None, "")
            }
            item["label"] = label
            if outcome.best_objective is not None and main_best is not None:
                item["vs_main_best_feasible"] = (
                    outcome.best_objective - main_best
                ) / max(abs(main_best), 1e-300)
            results.append(item)
        return {
            "made": self.explorations_made,
            "max": self.pilot.exploration.max_explorations
            if self.pilot.exploration
            else 0,
            "running": list(explorer.running),
            "finished": [
                label
                for label, outcome in self.explored.items()
                if not outcome.error and Path(outcome.state_path).is_file()
            ],
            "main": main,
            "results": results,
        }

    def _forecast(self, decision: Decision) -> None:
        """Keep the prediction of a decision, to read it when it falls due."""
        assessment = decision.assessment
        if assessment is None or assessment.prediction is None or not self.reports:
            return
        prediction = assessment.prediction
        last = self.reports[-1]
        self.forecasts.append(
            _Forecast(
                decision,
                prediction,
                float(last[_METRICS[prediction.metric]]),
                int(last["iteration"]) + prediction.within,
            )
        )

    def _read_forecasts(self) -> None:
        """Read the predictions that fall due: did the run do what Claude said?

        The verdict goes to Claude with its decision, and the record of its
        predictions with the next call: a calibration of its confidence.
        """
        if not self.forecasts or not self.reports:
            return
        iteration = int(self.reports[-1]["iteration"])
        waiting = []
        for forecast in self.forecasts:
            if iteration < forecast.due:
                waiting.append(forecast)
                continue
            now = float(self.reports[-1][_METRICS[forecast.prediction.metric]])
            result = verdict(forecast.prediction, forecast.before, now)
            self.record["made"] += 1
            self.record["confirmed"] += int(result.held)
            self._note_outcome(forecast.decision, f"Prediction: {result.text}")
            self.pilot.journal.write(
                "forecast", held=result.held, text=result.text, iteration=iteration
            )
        self.forecasts = waiting

    def _set_review(self, requested: int) -> None:
        """Consult Claude again after the outer iterations it asked for, bounded.

        Never fewer than one, nor more than ``MAX_REVIEW``, nor more than half of
        the iterations left (a run near its end is followed closely).
        """
        if not self.pilot.adaptive_review or not self.reports:
            return
        left = self._iterations_left()
        iterations = max(1, min(requested, MAX_REVIEW, left // 2))
        self.advisor.triggers.set_review(iterations)
        self.pilot.journal.write("review", requested=requested, iterations=iterations)
        LOGGER.info("Claude pilot: consulted again in %d iterations.", iterations)

    def _iterations_left(self) -> int:
        """The outer iterations the evaluations left allow, at the rate of the run."""
        last = self.reports[-1]
        per_iteration = max(
            float(last.get("evaluation") or 0) / max(int(last["iteration"]), 1), 1.0
        )
        return int(max(self.budget - len(self.problem.database), 0) / per_iteration)

    def _timing(self) -> dict[str, Any]:
        """How long an iteration and a call take, to choose how often to consult.

        The suggestion keeps the calls under ``OVERHEAD_SHARE`` of the time.
        """
        reports = [r for r in self.reports if "branch" not in r][-TIMING_WINDOW:]
        timing: dict[str, Any] = {}
        if reports:
            seconds = median(
                float(r["model_time"]) + float(r["optimizer_time"]) for r in reports
            )
            timing["seconds_per_iteration"] = round(seconds, 2)
        latencies = self.advisor.latencies
        if latencies:
            timing["seconds_per_call"] = round(median(latencies), 1)
        if len(timing) == 2:
            suggested = math.ceil(
                timing["seconds_per_call"]
                / (OVERHEAD_SHARE * max(timing["seconds_per_iteration"], 1e-3))
            )
            timing["suggested_review_in"] = max(1, min(suggested, MAX_REVIEW))
        review = self.advisor.triggers.review
        if review is not None:
            timing["review_in"] = review
        return timing

    def _age(self, evaluation: int, iteration: int) -> tuple[int, bool]:
        """How old a decision is, and whether it is too old to be applied.

        In outer iterations for an LSO algorithm, in evaluations otherwise.
        """
        if iteration >= 0 and self.reports:
            age = int(self.reports[-1]["iteration"]) - iteration
            return age, age > DECISION_EXPIRY_ITERATIONS
        age = len(self.problem.database) - evaluation
        return age, age > DECISION_EXPIRY

    @property
    def proposal_id(self) -> str:
        """The id of the open proposal, or nothing."""
        return "" if self.proposal is None else self.proposal.id

    def _take_commands(self) -> None:
        """Apply the commands of the user received since the last look."""
        for name, params in events.take_commands():
            self.pilot.journal.write("user", command=name, params=params)
            if name == "copilot.accept" and params.get("id") == self.proposal_id:
                assert self.proposal is not None
                _, expired = self._age(
                    self.proposal.evaluation, self.proposal.iteration
                )
                if expired:
                    self._close_proposal("expired")
                else:
                    self.pending = self.proposal.decision
                    self._close_proposal("accepted")
            elif name == "copilot.reject" and params.get("id") == self.proposal_id:
                self._close_proposal("rejected")
            elif name == "copilot.mode" and params.get("mode") in PILOT_MODES:
                self._set_mode(params["mode"])
            elif name == "copilot.ask" and str(params.get("text", "")).strip():
                self.questions.append(str(params["text"]).strip())
            elif name == "stop":
                self.stopped = True

    def _close_proposal(self, how: str) -> None:
        assert self.proposal is not None
        self.pilot.journal.write("proposal_closed", id=self.proposal.id, how=how)
        _publish("copilot.message", kind="closed", id=self.proposal.id, how=how)
        self.proposal = None

    def _set_mode(self, mode: PilotMode) -> None:
        """Change the mode during the run; the open proposal stays open."""
        self.mode = mode
        self.limits = self._limits()
        self.advisor.limits = self.limits
        if mode == "pilot" and self.proposal is not None:
            self.pending = self.proposal.decision
            self._close_proposal("accepted")
        _publish("copilot.status", state="watching", mode=mode)

    def _limits(self) -> Limits:
        allowed: Sequence[ActionKind] | None = self.pilot.allowed_actions
        if self.mode == "observer":
            allowed = ()
        limits = Limits.of(self.original, allowed, self.pilot.max_restarts)
        exploration = self.pilot.exploration
        return replace(
            limits,
            require_assessment=self.pilot.critical_review,
            exploration=exploration is not None,
            max_exploration_processes=exploration.max_processes if exploration else 0,
            max_exploration_iterations=exploration.max_iterations if exploration else 0,
            max_explorations=exploration.max_explorations if exploration else 0,
        )

    def _apply(self, decision: Decision) -> str:
        """Apply a decision to the next segment; return why it starts."""
        action = decision.action
        if isinstance(action, ChangeSettings):
            self.settings.update(action.settings)
        elif isinstance(action, SwitchAlgorithm):
            self.algo_name = action.algo_name
            self.settings = dict(action.settings)
        elif isinstance(action, ChangeDesignSpace):
            self._change_bounds(action.variables)
        elif isinstance(action, AddSamples):
            self.algo_name = action.algo_name
            self.settings = {**action.settings, "n_samples": action.n_samples}
            self.region = list(action.region)
        elif isinstance(action, ChangeSubScenario):
            self._change_sub_scenario(action)
        elif isinstance(action, Restart):
            self._restart(action)
        elif isinstance(action, Steer):
            space = self.problem.design_space
            space.set_current_value(self._steered(action))
        elif isinstance(action, Compare):
            self._compare(decision, action)
        elif isinstance(action, Adopt):
            self._adopt(action)
        self.result.decisions.append(decision)
        self.pilot.journal.write("decision", decision=decision)
        return f"{action.kind}: {decision.rationale or decision.diagnosis}"

    def _change_bounds(self, changes: list[VariableChange]) -> None:
        """New bounds and starting values of some design variables."""
        space = self.problem.design_space
        for change in changes:
            size = space.get_size(change.name)
            lower = space.get_lower_bound(change.name)
            upper = space.get_upper_bound(change.name)
            if change.lower is not None:
                lower = np.broadcast_to(change.lower, size).astype(float)
            if change.upper is not None:
                upper = np.broadcast_to(change.upper, size).astype(float)
            value = space.get_current_value([change.name])
            if change.value is not None:
                value = np.broadcast_to(change.value, size).astype(float)
            # GEMSEO does not check the value against the bounds: the pilot does.
            space.set_lower_bound(change.name, lower)
            space.set_upper_bound(change.name, upper)
            space.set_current_variable(change.name, np.clip(value, lower, upper))

    def _restart(self, action: Restart) -> None:
        """Start the next segment from a design transformed on its grid."""
        source = self.design
        assert source is not None
        entries = database_entries(self.problem)
        view = source.view(entries, self._snapshot(), None, self.restarts)
        base = view.point(action.base, entries)
        value, record = source.restart(
            view,
            action.base,
            action.transforms,
            entries,
            len(entries),
            action.answers,
        )
        space = self.problem.design_space
        if base.evaluation >= 0:
            x = np.asarray(entries[base.evaluation][0], dtype=float)
            space.set_current_value(
                np.clip(x, space.get_lower_bounds(), space.get_upper_bounds())
            )
        name = source.description.variable
        space.set_current_variable(
            name,
            np.clip(value, space.get_lower_bound(name), space.get_upper_bound(name)),
        )
        self.restarts.append(record)
        self.pilot.journal.write("restart", **asdict(record))
        LOGGER.info("Claude pilot: restart from a new design (%s).", action.answers)

    def _iterates(self, count: int) -> list[int]:
        """The evaluations of the iterates.

        Those of the outer iterations of an LSO algorithm, else every evaluation.
        """
        iterates = [
            int(report["evaluation"]) - 1
            for report in self.reports
            if 0 < int(report["evaluation"]) <= count
        ]
        return iterates or list(range(count))

    def _steered(self, action: Steer) -> Any:
        """The design vector a steering moves to, from the last iterate."""
        entries = database_entries(self.problem)
        space = self.problem.design_space
        if not entries:
            return space.get_current_value()
        iterates = self._iterates(len(entries))
        x = np.array(entries[iterates[-1]][0], dtype=float)
        return self._compose(
            x, entries, iterates, action.anticipate, action.transforms, action.variables
        )

    def _compose(
        self,
        x: Any,
        entries: Any,
        iterates: list[int],
        anticipate: Any,
        transforms: Any,
        variables: Any,
    ) -> Any:
        """A design from another: its trend extended, transformed, some values set."""
        space = self.problem.design_space
        if anticipate is not None:
            span = min(anticipate.iterations, len(iterates) - 1)
            if span > 0:
                past = np.asarray(entries[iterates[-1 - span]][0], dtype=float)
                x = x + anticipate.factor * (x - past)
        lower, upper = space.get_lower_bounds(), space.get_upper_bounds()
        x = np.clip(x, lower, upper)
        if transforms and self.design is not None:
            view = self.design.view(
                entries, self._snapshot(), None, self.restarts, iterates=iterates
            )
            x = self.design.transform(view, x, transforms, entries)
        start = 0
        for variable in self.original.variables:
            change = next(
                (item for item in variables if item.name == variable.name), None
            )
            if change is not None:
                x[start : start + variable.size] = np.broadcast_to(
                    np.asarray(change.value, dtype=float), variable.size
                )
            start += variable.size
        return np.clip(x, lower, upper)

    def _restore_bounds(self) -> None:
        """Give back the bounds the user set."""
        space = self.problem.design_space
        for variable in self.original.variables:
            space.set_lower_bound(variable.name, variable.lower)
            space.set_upper_bound(variable.name, variable.upper)

    def _change_sub_scenario(self, action: ChangeSubScenario) -> None:
        """Set another algorithm or other settings on a sub-optimization."""
        sub = next(
            item
            for item in self.scenario.formulation.get_sub_scenarios()
            if item.name == action.scenario
        )
        current = sub._settings
        current_name = str(getattr(current.algo_name, "value", current.algo_name))
        name = action.algo_name or current_name
        settings = dict(current.algo_settings) if name == current_name else {}
        sub.set_algorithm(algo_name=name, **{**settings, **action.settings})

    def _warm_start(self) -> None:
        """Start the next segment from the best point, inside the current bounds."""
        history = history_from_entries(database_entries(self.problem), self._snapshot())
        if history.best_index < 0:
            return
        space = self.problem.design_space
        lower = space.get_lower_bounds()
        upper = space.get_upper_bounds()
        space.set_current_value(np.clip(history.best_x, lower, upper))

    def _report(self, text: str) -> None:
        """Keep the analysis of the run written by Claude, next to the journal.

        The final design and its restarts follow, drawn from the model.
        """
        if not text:
            return
        text += self._design_report()
        self.result.report = text
        path = self.pilot.journal.path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            (path.parent / "report.md").write_text(text + "\n", encoding="utf-8")
        _publish("copilot.message", kind="report", text=text)

    def _design_report(self) -> str:
        """The final design and the restarts, as maps; nothing without a design."""
        if self.design is None:
            return ""
        view = self.design.view(
            database_entries(self.problem), self._snapshot(), None, self.restarts
        )
        point = view.main_point()
        if point is None:
            return ""
        parts = [
            "",
            "## The design",
            "",
            "```",
            view.text_map(view.density_name(point), point),
            "```",
        ]
        for index, record in enumerate(self.restarts, 1):
            parts += [
                "",
                f"### Restart {index}, after {record.evaluation} evaluations",
                "",
                record.answers,
                "",
                "Before:",
                "",
                "```",
                record.map_before,
                "```",
                "",
                "Restarted from:",
                "",
                "```",
                record.map_after,
                "```",
            ]
        return "\n".join(parts)

    def _finish(self) -> None:
        """Answer the last questions, write the report, give back the design space."""
        if self.proposal is not None:
            self._close_proposal("run ended")
        self._take_commands()
        self._answer_questions()
        report = self.pilot.report
        wanted = report() if callable(report) else report
        if wanted and not self.advisor.disabled:
            self._handle(self._ask_now("report"))
        self._restore_bounds()
        space = self.problem.design_space
        history = history_from_entries(database_entries(self.problem), self._snapshot())
        self.result.best_evaluation = history.best_index
        if history.best_index >= 0:
            space.set_current_value(history.best_x)
        self.result.usage = self.advisor.usage
        self.result.disabled = self.advisor.disabled
        summary = {
            "stop_reason": self.result.stop_reason,
            "segments": [asdict(segment) for segment in self.result.segments],
            "decisions": len(self.result.decisions),
            "best_evaluation": history.best_index,
            "evaluations": history.n_evaluations,
            "disabled": self.result.disabled,
            "usage": asdict(self.result.usage),
            "calls": self.advisor.calls,
            "report": bool(self.result.report),
        }
        self.pilot.journal.write("status", state="finished", **summary)
        _publish("copilot.summary", **summary)
        _publish("copilot.status", state="off", reason=self.result.stop_reason)

    def _publish_usage(self) -> None:
        _publish(
            "copilot.usage", calls=self.advisor.calls, **asdict(self.advisor.usage)
        )

    def _snapshot(self) -> ProblemSnapshot:
        """The problem as it is now."""
        sub_scenarios = sub_scenarios_of(self.scenario)
        snapshot = snapshot_problem(
            self.problem,
            self.algo_name,
            self.budget,
            self.settings,
            driver_kind=self.kind,
            formulation=type(self.scenario.formulation).__name__,
            components=components_of(self.scenario, self.pilot.data_level == "full"),
            sub_scenarios=sub_scenarios,
            # The system of a BiLevel study has no gradients.
            gradients="none" if sub_scenarios else None,
        )
        if self.reports:
            snapshot = replace(
                snapshot, algorithm_state=tuple(self.reports[-ALGORITHM_REPORTS:])
            )
        return snapshot

    def _check(
        self, trigger: TriggerKind | None, done: int | None = None, question: str = ""
    ) -> Check:
        """A check of the run, prepared in the optimizer's thread."""
        entries = database_entries(self.problem)
        if done is not None:
            entries = entries[:done]
        allowed = sorted(
            self.limits.allowed_actions & ACTIONS_OF_DRIVER[self.original.driver_kind]
        )
        if self.design is None:
            allowed = [kind for kind in allowed if kind != "restart"]
        snapshot = self._snapshot()
        design = None
        if self.design is not None:
            # In the optimizer's thread: the model is not computing meanwhile.
            design = self.design.view(
                entries,
                snapshot,
                self.live,
                self.restarts,
                start_x=self.problem.design_space.get_current_value(),
                iterates=self._iterates(len(entries)),
            )
        pilot: dict[str, Any] = {
            "mode": self.mode,
            "allowed_actions": allowed,
            "segment": len(self.result.segments),
            "evaluation_budget": self.budget,
        }
        if self.design is not None:
            pilot["restarts"] = len(self.restarts)
            pilot["max_restarts"] = self.pilot.max_restarts
        if self.algo_name in LSO_ALGORITHMS and self.pilot.adaptive_review:
            pilot["timing"] = self._timing()
        if self.record["made"]:
            pilot["track_record"] = dict(self.record)
        if self.explorer is not None and self.algo_name in LSO_ALGORITHMS:
            pilot["explorations"] = self._exploration_context()
        if self.algo_name in LSO_ALGORITHMS:
            pilot["comparisons"] = self.comparisons
            pilot["max_comparisons"] = self.limits.max_comparisons
        return Check(snapshot, entries, pilot, trigger, question, design)


_METRICS = {
    "objective": "objective",
    "max_constraint": "max_constraint",
    "kkt_residual": "kkt_residual",
}
"""The field of a report each metric of a prediction is read in."""


def _algorithm_of(method: str) -> str:
    """The GEMSEO algorithm of a method of the large-scale optimizer."""
    return next(name for name, value in LSO_ALGORITHMS.items() if value == method)


def _publish(event: str, **payload: Any) -> None:
    events.publish(event, payload)


def _report_data(report: Any) -> dict[str, Any]:
    """The report of an outer iteration as plain data."""
    data = (
        asdict(report)
        if is_dataclass(report) and not isinstance(report, type)
        else dict(report)
    )
    return {
        name: list(value) if isinstance(value, tuple) else value
        for name, value in data.items()
    }


def _unavailable(backend: Backend | LoopingBackend | None) -> str:
    """Why a backend cannot be used, from its check if it has one; or nothing."""
    check = getattr(backend, "check", None)
    if check is None:
        return ""
    status = check()
    return "" if status.ok else str(status.message)


def _default_max_iter(algo_name: str) -> int:
    """The default ``max_iter`` of an optimization algorithm."""
    algorithm = gemseo_algorithms("optimization")[algo_name]
    return int(algorithm.settings_model.model_fields["max_iter"].default)


def _journal_path(journal: Path | str | Literal[False] | None) -> Path | None:
    if journal is False:
        return None
    if journal is not None:
        return Path(journal)
    folder = os.environ.get(FOLDER_VARIABLE)
    if folder:
        return Path(folder) / "journal.jsonl"
    script = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if script is not None and script.suffix == ".py":
        return script.with_suffix(".pilot") / "journal.jsonl"
    return Path.cwd() / "claude_pilot" / "journal.jsonl"
