"""Exploring other zones of the design space, in processes Claude does not guide."""

import json
import logging
from dataclasses import replace

import numpy as np
import pytest
from gemseo import create_design_space
from gemseo import create_scenario
from pilot_samples import problem as problem_snapshot
from test_lso_pilot import FINE
from test_lso_pilot import Local
from test_lso_pilot import scenario

from gemseo_claude_pilot import ClaudePilot
from gemseo_claude_pilot.backends import FakeBackend
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.exploration import ExplorationSettings
from gemseo_claude_pilot.exploration import Explorer
from gemseo_claude_pilot.exploration import Handle
from gemseo_claude_pilot.exploration import Job
from gemseo_claude_pilot.exploration import run_exploration
from gemseo_claude_pilot.guardrails import Limits
from gemseo_claude_pilot.guardrails import RejectedDecisionError
from gemseo_claude_pilot.guardrails import check
from gemseo_claude_pilot.journal import read_journal
from gemseo_claude_pilot.triggers import TriggerSettings
from gemseo_lso.benchmarks.synthetic import LocalConstraints

logging.getLogger("gemseo").setLevel(logging.WARNING)
logging.getLogger("gemseo_lso").setLevel(logging.WARNING)

SIZE = 60


class Done(Handle):
    """An exploration that has already ended: the tests run no process."""

    def __init__(self, job, threads, timeout):
        self.outcome = run_exploration(job)

    def poll(self):
        return self.outcome

    def stop(self):
        pass


def job(tmp_path, iterations=3, x0=0.9, label="a", factory=scenario):
    return Job(
        label,
        factory,
        "LSO_MMA",
        {"max_iter": 100},
        [x0] * SIZE,
        iterations,
        str(tmp_path / f"{label}.h5"),
    )


# The work of a process.


def test_an_exploration_runs_a_few_iterations_and_saves_its_state(tmp_path):
    outcome = run_exploration(job(tmp_path))
    assert outcome.error == ""
    assert outcome.iterations == 3
    assert outcome.evaluations >= 3
    assert outcome.best_objective is not None
    assert len(outcome.best_x) == SIZE
    assert outcome.final_violation <= 1e-3  # It ends on a feasible point.
    assert (tmp_path / "a.h5").is_file()


def test_a_failed_exploration_says_so(tmp_path):
    def broken():
        raise RuntimeError("no model")

    outcome = run_exploration(job(tmp_path, factory=broken))
    assert "RuntimeError: no model" in outcome.error
    assert outcome.best_x is None


def test_the_explorer_follows_its_processes(tmp_path):
    settings = ExplorationSettings(factory=scenario, launch=Done)
    explorer = Explorer(settings)
    explorer.start([job(tmp_path, label="a"), job(tmp_path, label="b", x0=0.95)])
    assert explorer.active
    outcomes = explorer.poll()
    assert sorted(outcome.label for outcome in outcomes) == ["a", "b"]
    assert not explorer.active
    explorer.stop()


# The guardrails.


def decision(action):
    return Decision.model_validate(
        {
            "diagnosis": "d",
            "action": action,
            "assessment": {
                "hypotheses": [
                    {"claim": "c", "evidence_for": "e", "evidence_against": "a"}
                ],
                "weaknesses": ["w"],
                "alternatives": [{"action": "none", "why_not": "n"}],
                "prediction": {"metric": "objective", "expect": "falls", "within": 3},
            },
        }
    )


def lso_problem():
    state = tuple(
        {
            "iteration": i,
            "evaluation": 3 * i,
            "objective": 1.0,
            "max_constraint": 0.0,
            "kkt_residual": 0.1,
        }
        for i in range(1, 6)
    )
    return problem_snapshot(
        algo_name="LSO_MMA", evaluation_budget=600, algorithm_state=state
    )


def explore(**changes):
    start = {"label": "wide", "why": "A far zone.", "perturb": {"scale": 0.2}}
    return {"kind": "explore", "starts": [start], "iterations": 50, **changes}


def limits(**changes):
    snapshot = lso_problem()
    return snapshot, Limits.of(snapshot).__class__(
        snapshot.variables,
        snapshot.evaluation_budget,
        exploration=True,
        max_explorations=2,
        **changes,
    )


def test_an_exploration_within_the_limits_is_accepted_and_clipped():
    snapshot, allowed = limits(max_exploration_iterations=20)
    checked = check(decision(explore()), snapshot, allowed, 15, explorations={})
    assert checked.decision.action.iterations == 20
    assert any("20 outer iterations at most" in note for note in checked.notes)


@pytest.mark.parametrize(
    ("action", "state", "message"),
    [
        (explore(), {"made": 2}, "2 explorations of this run are used"),
        (explore(), {"running": ["x"]}, "still running"),
        (
            explore(starts=[{"label": "a", "why": "w", "base": "current"}]),
            {},
            "current iterate itself",
        ),
        (
            explore(
                starts=[
                    {"label": "a", "why": "w", "perturb": {"scale": 0.1}},
                    {"label": "a", "why": "w", "perturb": {"scale": 0.2}},
                ]
            ),
            {},
            "labels of the starts must differ",
        ),
        (
            explore(
                starts=[
                    {
                        "label": "a",
                        "why": "w",
                        "variables": [{"name": "y", "value": 1.0}],
                    }
                ]
            ),
            {},
            "no design variable named y",
        ),
    ],
)
def test_an_exploration_beyond_the_limits_is_refused(action, state, message):
    snapshot, allowed = limits(max_exploration_iterations=50)
    with pytest.raises(RejectedDecisionError, match=message):
        check(decision(action), snapshot, allowed, 15, explorations=state)


def test_exploring_needs_the_means_to_build_the_problem_elsewhere():
    snapshot = lso_problem()
    with pytest.raises(RejectedDecisionError, match="no scenario factory"):
        check(decision(explore()), snapshot, Limits.of(snapshot), 15, explorations={})


def test_only_an_ended_exploration_is_adopted():
    snapshot, allowed = limits()
    adopt = {"kind": "adopt", "exploration": "wide"}
    with pytest.raises(RejectedDecisionError, match="no ended exploration named wide"):
        check(decision(adopt), snapshot, allowed, 15, explorations={"finished": []})
    check(decision(adopt), snapshot, allowed, 15, explorations={"finished": ["wide"]})


# In a run.


class Exploring(FakeBackend):
    """Explores at its first call, adopts the exploration when it has ended."""

    def __init__(self):
        super().__init__([], then=FINE)
        self.explored = False

    def send(self, request):
        context = json.loads(request.messages[0].text)
        action = None
        if not self.explored and context["trigger"] != "exploration":
            self.explored = True
            action = {
                "kind": "explore",
                "iterations": 10,
                "starts": [
                    {
                        "label": "wide",
                        "why": "A zone far from the current design.",
                        "perturb": {"scale": 0.1, "seed": 3},
                    }
                ],
            }
        elif context["trigger"] == "exploration":
            finished = context["pilot"]["explorations"]["finished"]
            assert finished, "the exploration ended: it can be adopted"
            action = {"kind": "adopt", "exploration": finished[0]}
        if action is None:
            return super().send(request)
        self._then = FakeBackend.decision({"diagnosis": "d", "action": action})
        try:
            return super().send(request)
        finally:
            self._then = FINE


def test_claude_explores_then_moves_its_main_run_onto_an_exploration(tmp_path):
    path = tmp_path / "journal.jsonl"
    pilot = ClaudePilot(
        mode="pilot",
        backend=Exploring(),
        triggers=TriggerSettings(
            period=None, launch_pause=0.0, min_interval=0, start=False, events=False
        ),
        journal=path,
        report=False,
        exploration=ExplorationSettings(
            factory=scenario, launch=Done, max_iterations=3
        ),
    )
    study = scenario()
    study.formulation.optimization_problem.design_space.set_current_value(
        np.full(SIZE, 0.5)
    )
    result = pilot.execute(study, "LSO_MMA", max_iter=16)
    journal = list(read_journal(path))
    kinds = [record["kind"] for record in journal]
    assert kinds.count("exploration") == 1
    (outcome,) = [r for r in journal if r["kind"] == "exploration_result"]
    assert outcome["label"] == "wide"
    assert outcome["why"] == "A zone far from the current design."
    assert outcome["iterations"] == 3  # Clipped by the user's limit.
    assert kinds.count("adoption") == 1
    # The run goes on in a new segment, from the exploration's state.
    assert result.segments[-1].algo_name == "LSO_MMA"
    assert len(result.segments) >= 2
    assert [d.action.kind for d in result.decisions][:2] == ["explore", "adopt"]


class Slow(Done):
    """An exploration still running when the main run, a few iterations, ends."""

    def __init__(self, job, threads, timeout):
        super().__init__(job, threads, timeout)
        self.looks = 0

    def poll(self):
        self.looks += 1
        return self.outcome if self.looks > 40 else None


def test_the_run_waits_for_its_explorations_when_it_ends_first(tmp_path, monkeypatch):
    import gemseo_claude_pilot.pilot as pilot_module

    monkeypatch.setattr(pilot_module, "EXPLORATION_POLL", 0.0)
    path = tmp_path / "journal.jsonl"
    pilot = ClaudePilot(
        mode="pilot",
        backend=Exploring(),
        # One call, at the first iteration: it explores. The run then ends.
        triggers=TriggerSettings(
            period=None,
            first_iteration=True,
            launch_pause=None,
            period_iterations=None,
            min_interval=0,
            start=False,
            events=False,
        ),
        journal=path,
        report=False,
        exploration=ExplorationSettings(
            factory=scenario, launch=Slow, max_iterations=3
        ),
    )
    study = scenario()
    study.formulation.optimization_problem.design_space.set_current_value(
        np.full(SIZE, 0.5)
    )
    # The tolerance ends the run well before its budget.
    result = pilot.execute(study, "LSO_MMA", max_iter=40, ftol_rel=3e-2)
    journal = list(read_journal(path))
    kinds = [record["kind"] for record in journal]
    # The exploration ended after the main run had: Claude still read it.
    assert kinds.count("exploration_result") == 1
    triggers = [r["trigger"] for r in journal if r["kind"] == "call"]
    assert "exploration" in triggers
    assert kinds.count("adoption") == 1
    assert len(result.segments) >= 2


class Twice(FakeBackend):
    """Explores at its first call, explores again once the first ended, then adopts."""

    def __init__(self):
        super().__init__([], then=FINE)
        self.readings = 0

    def send(self, request):
        context = json.loads(request.messages[0].text)
        action = None
        if context["trigger"] == "exploration":
            self.readings += 1
            finished = context["pilot"]["explorations"]["finished"]
            if self.readings == 1:
                action = {
                    "kind": "explore",
                    "iterations": 10,
                    "starts": [
                        {
                            "label": "second",
                            "why": "Another start.",
                            "perturb": {"scale": 0.3},
                        }
                    ],
                }
            else:
                action = {"kind": "adopt", "exploration": finished[0]}
        elif context["trigger"] == "periodic" and not self.readings:
            action = {
                "kind": "explore",
                "iterations": 10,
                "starts": [
                    {"label": "first", "why": "A start.", "perturb": {"scale": 0.1}}
                ],
            }
        if action is None:
            return super().send(request)
        self._then = FakeBackend.decision({"diagnosis": "d", "action": action})
        try:
            return super().send(request)
        finally:
            self._then = FINE


def test_after_waiting_claude_may_explore_again_then_adopt(tmp_path, monkeypatch):
    import gemseo_claude_pilot.pilot as pilot_module

    monkeypatch.setattr(pilot_module, "EXPLORATION_POLL", 0.0)
    path = tmp_path / "journal.jsonl"
    pilot = ClaudePilot(
        mode="pilot",
        backend=Twice(),
        triggers=TriggerSettings(
            period=None,
            first_iteration=True,
            launch_pause=None,
            period_iterations=None,
            min_interval=0,
            start=False,
            events=False,
        ),
        journal=path,
        report=False,
        exploration=ExplorationSettings(
            factory=scenario, launch=Slow, max_iterations=3
        ),
    )
    study = scenario()
    study.formulation.optimization_problem.design_space.set_current_value(
        np.full(SIZE, 0.5)
    )
    result = pilot.execute(study, "LSO_MMA", max_iter=40, ftol_rel=3e-2)
    journal = list(read_journal(path))
    kinds = [record["kind"] for record in journal]
    assert kinds.count("exploration") == 2  # The second one, after the wait.
    assert kinds.count("exploration_result") == 2
    assert kinds.count("adoption") == 1
    labels = [r["label"] for r in journal if r["kind"] == "exploration_result"]
    assert labels == ["first", "second"]
    assert [d.action.kind for d in result.decisions][:3] == [
        "explore",
        "explore",
        "adopt",
    ]


class Stopping(Twice):
    """Explores at its first call, stops when it reads the exploration."""

    def send(self, request):
        context = json.loads(request.messages[0].text)
        if context["trigger"] == "exploration":
            self._then = FakeBackend.decision(
                {"diagnosis": "d", "action": {"kind": "stop", "reason": "converged"}}
            )
            try:
                return FakeBackend.send(self, request)
            finally:
                self._then = FINE
        return super().send(request)


def test_after_waiting_claude_may_stop_the_run(tmp_path, monkeypatch):
    import gemseo_claude_pilot.pilot as pilot_module

    monkeypatch.setattr(pilot_module, "EXPLORATION_POLL", 0.0)
    pilot = ClaudePilot(
        mode="pilot",
        backend=Stopping(),
        triggers=TriggerSettings(
            period=None,
            first_iteration=True,
            launch_pause=None,
            period_iterations=None,
            min_interval=0,
            start=False,
            events=False,
        ),
        journal=tmp_path / "journal.jsonl",
        report=False,
        exploration=ExplorationSettings(
            factory=scenario, launch=Slow, max_iterations=3
        ),
    )
    study = scenario()
    study.formulation.optimization_problem.design_space.set_current_value(
        np.full(SIZE, 0.5)
    )
    result = pilot.execute(study, "LSO_MMA", max_iter=40, ftol_rel=3e-2)
    assert result.stop_reason == "stopped by Claude"
    assert len(result.segments) == 1  # No other segment after the stop.


def test_an_exploration_is_ten_iterations_by_default():
    from gemseo_claude_pilot.decisions import Explore

    assert ExplorationSettings(factory=scenario).max_iterations == 10
    start = {"label": "a", "why": "w", "perturb": {"scale": 0.1}}
    assert Explore.model_validate({"starts": [start]}).iterations == 10


def test_an_exploration_tells_how_far_it_is(tmp_path):
    import json as json_module

    work = job(tmp_path, iterations=4)
    work = work.__class__(
        **{**work.__dict__, "progress_path": str(tmp_path / "p.json")}
    )
    outcome = run_exploration(work)
    data = json_module.loads((tmp_path / "p.json").read_text("utf-8"))
    assert data["of"] == 4
    assert data["iteration"] == outcome.iterations  # The last it made.
    assert {"objective", "max_constraint", "kkt_residual", "seconds", "outside"} <= set(
        data
    )
    assert data["gain_per_iteration"] is not None


class Following(Slow):
    """A running exploration that reports how far it is."""

    def poll(self):
        self.looks += 1
        return self.outcome if self.looks > 40 else None

    def progress(self):
        return {
            "iteration": self.looks,
            "of": 3,
            "objective": 0.5,
            "max_constraint": 0.0,
        }


def test_claude_follows_its_running_explorations(tmp_path, monkeypatch):
    import gemseo_claude_pilot.pilot as pilot_module

    monkeypatch.setattr(pilot_module, "EXPLORATION_POLL", 0.0)
    path = tmp_path / "journal.jsonl"
    pilot = ClaudePilot(
        mode="pilot",
        backend=Exploring(),
        triggers=TriggerSettings(
            period=None, launch_pause=0.0, min_interval=0, start=False, events=False
        ),
        journal=path,
        report=False,
        exploration=ExplorationSettings(
            factory=scenario, launch=Following, max_iterations=3
        ),
    )
    study = scenario()
    study.formulation.optimization_problem.design_space.set_current_value(
        np.full(SIZE, 0.5)
    )
    pilot.execute(study, "LSO_MMA", max_iter=10)
    journal = list(read_journal(path))
    # The journal keeps it, once per iteration of the exploration...
    seen = [r for r in journal if r["kind"] == "exploration_progress"]
    assert seen and seen[0]["label"] == "wide"
    assert [r["iteration"] for r in seen] == sorted({r["iteration"] for r in seen})
    # ...and Claude reads it at its consultations while the exploration runs.
    contexts = [json.loads(r["context"]) for r in journal if r["kind"] == "call"]
    followed = [
        c["pilot"]["explorations"]["progress"]
        for c in contexts
        if c["pilot"]["explorations"]["progress"]
    ]
    assert followed
    assert followed[0][0]["label"] == "wide"
    assert "vs_main_current" in followed[0][0]


# The threads and the memory.


@pytest.mark.parametrize(
    ("free", "starts"),
    [(40.0, 3), (20.0, 3), (17.0, 2), (9.0, 2), (2.0, 2)],  # 2 at least, 3 at most.
)
def test_the_memory_available_sets_how_many_explorations_run_at_once(
    monkeypatch, free, starts
):
    import gemseo_claude_pilot.exploration as exploration_module

    monkeypatch.setattr(exploration_module, "available_memory_gb", lambda: free)
    explorer = Explorer(ExplorationSettings(factory=scenario, launch=Done))
    assert explorer.max_starts() == starts  # (free - 4 GB) // 5 GB, in [2, 3].


def test_without_a_way_to_read_the_memory_the_most_run(monkeypatch):
    import gemseo_claude_pilot.exploration as exploration_module

    monkeypatch.setattr(exploration_module, "available_memory_gb", lambda: None)
    explorer = Explorer(ExplorationSettings(factory=scenario, launch=Done))
    assert explorer.max_starts() == 3


def test_the_memory_of_this_machine_can_be_read():
    from gemseo_claude_pilot.exploration import available_memory_gb

    free = available_memory_gb()
    assert free is None or free > 0.1


def test_an_exploration_has_twice_the_threads_the_shared_cores_give(monkeypatch):
    import os

    monkeypatch.setattr(os, "cpu_count", lambda: 12)
    explorer = Explorer(ExplorationSettings(factory=scenario, launch=Done))
    assert explorer.threads == 4  # Twice 12 // 5.
    explicit = Explorer(ExplorationSettings(factory=scenario, threads=6, launch=Done))
    assert explicit.threads == 6


def test_more_starts_than_the_memory_allows_are_refused():
    snapshot, allowed = limits(max_exploration_iterations=10)
    starts = [
        {"label": name, "why": "w", "perturb": {"scale": 0.1 * (i + 1)}}
        for i, name in enumerate("abc")
    ]
    state = {"max_starts": 2, "free_memory_gb": 9.0}
    with pytest.raises(RejectedDecisionError, match="at most 2 explorations at a time"):
        check(
            decision(explore(starts=starts)), snapshot, allowed, 15, explorations=state
        )
    check(
        decision(explore(starts=starts[:2])), snapshot, allowed, 15, explorations=state
    )


# Claude may interrupt its explorations.


def test_an_exploration_asked_to_stop_ends_early_on_a_feasible_point(tmp_path):
    stop = tmp_path / "a.stop"
    stop.write_text("stop", "utf-8")  # Asked to stop before it starts.
    work = job(tmp_path, iterations=8)
    work = work.__class__(**{**work.__dict__, "stop_path": str(stop)})
    outcome = run_exploration(work)
    assert outcome.error == ""
    assert 1 <= outcome.iterations < 8  # At the end of its first iteration.
    assert outcome.final_violation <= 1e-3  # On a feasible point...
    assert (tmp_path / "a.h5").is_file()  # ...with its state saved: adoptable.


class Interruptible(Done):
    """A running exploration that ends when it is asked to."""

    def __init__(self, job, threads, timeout):
        super().__init__(job, threads, timeout)
        self.asked = False

    def poll(self):
        return self.outcome if self.asked else None

    def interrupt(self):
        self.asked = True


def test_the_explorer_interrupts_those_that_run(tmp_path):
    explorer = Explorer(ExplorationSettings(factory=scenario, launch=Interruptible))
    explorer.start([job(tmp_path, label="a"), job(tmp_path, label="b", x0=0.95)])
    assert explorer.poll() == []  # Both run.
    assert explorer.interrupt(["a", "nothing"]) == ["a"]
    assert [outcome.label for outcome in explorer.poll()] == ["a"]
    assert explorer.interrupt() == ["b"]  # All the running ones by default.
    assert [outcome.label for outcome in explorer.poll()] == ["b"]


def test_only_a_running_exploration_can_be_stopped():
    snapshot, allowed = limits(max_exploration_iterations=10)
    stop = {"kind": "stop_explorations", "explorations": ["wide"]}
    with pytest.raises(RejectedDecisionError, match="no exploration is running"):
        check(decision(stop), snapshot, allowed, 15, explorations={"running": []})
    with pytest.raises(
        RejectedDecisionError, match="no running exploration named wide"
    ):
        check(
            decision(stop), snapshot, allowed, 15, explorations={"running": ["other"]}
        )
    check(decision(stop), snapshot, allowed, 15, explorations={"running": ["wide"]})
    everything = {"kind": "stop_explorations"}  # None named: all of them.
    check(decision(everything), snapshot, allowed, 15, explorations={"running": ["a"]})


class Interrupting(Exploring):
    """Explores at its first call, stops its explorations at the next one."""

    def __init__(self):
        super().__init__()
        self.interrupted = False

    def send(self, request):
        context = json.loads(request.messages[0].text)
        running = context["pilot"].get("explorations", {}).get("running")
        if self.explored and running and not self.interrupted:
            self.interrupted = True
            self._then = FakeBackend.decision(
                {"diagnosis": "d", "action": {"kind": "stop_explorations"}}
            )
            try:
                return FakeBackend.send(self, request)
            finally:
                self._then = FINE
        if self.explored and context["trigger"] == "exploration":
            return FakeBackend.send(self, request)  # It reads the results only.
        return super().send(request)


def interrupting_pilot(path, launch, **triggers):
    return ClaudePilot(
        mode="pilot",
        backend=Interrupting(),
        triggers=TriggerSettings(period=None, min_interval=0, start=False, **triggers),
        journal=path,
        report=False,
        exploration=ExplorationSettings(
            factory=scenario, launch=launch, max_iterations=3
        ),
    )


def start_at(study, value=0.5):
    problem = study.formulation.optimization_problem
    problem.design_space.set_current_value(np.full(SIZE, value))
    return study


def test_claude_interrupts_its_explorations(tmp_path):
    path = tmp_path / "journal.jsonl"
    pilot = interrupting_pilot(path, Interruptible, launch_pause=0.0, events=False)
    result = pilot.execute(start_at(scenario()), "LSO_MMA", max_iter=10)
    kinds = [record["kind"] for record in read_journal(path)]
    assert kinds.count("exploration") == 1
    assert kinds.count("exploration_interrupted") == 1
    # The interrupted exploration still reports what it reached.
    assert kinds.count("exploration_result") == 1
    assert [d.action.kind for d in result.decisions][:2] == [
        "explore",
        "stop_explorations",
    ]


def test_a_waiting_run_consults_claude_who_may_interrupt(tmp_path, monkeypatch):
    import gemseo_claude_pilot.pilot as pilot_module

    monkeypatch.setattr(pilot_module, "EXPLORATION_POLL", 0.0)
    monkeypatch.setattr(pilot_module, "EXPLORATION_CONSULT", 0.0)
    path = tmp_path / "journal.jsonl"
    # One call, at the first iteration, which explores; the run then converges
    # (tolerance) before the exploration, which only ends when it is asked to.
    pilot = interrupting_pilot(
        path,
        Interruptible,
        first_iteration=True,
        launch_pause=None,
        period_iterations=None,
        events=False,
    )
    pilot.execute(start_at(scenario()), "LSO_MMA", max_iter=40, ftol_rel=3e-2)
    kinds = [r["kind"] for r in read_journal(path)]
    assert kinds.count("exploration_interrupted") == 1
    assert kinds.count("exploration_result") == 1


# A start outside the feasible domain has a budget of its own to leave it.


class Outside(Local):
    """The synthetic problem, where a third of the constraints are active at the
    solution and violated at the start: a start outside the feasible domain."""

    def __init__(self):
        super().__init__()
        self.problem = LocalConstraints(SIZE, active_share=0.6, seed=3)


def outside_scenario():
    space = create_design_space()
    space.add_variable("x", size=SIZE, lower_bound=0.0, upper_bound=1.0, value=0.5)
    study = create_scenario([Outside()], "f", space, formulation_name="DisciplinaryOpt")
    study.add_constraint("g", "ineq")
    return study


def test_a_start_outside_the_domain_is_iterated_and_says_how_saturated_it_was(tmp_path):
    outcome = run_exploration(job(tmp_path, x0=0.5, factory=outside_scenario))
    assert outcome.error == ""
    assert outcome.saturation > 0.25
    assert outcome.exit_iterations >= 1
    assert outcome.iterations == 3  # The iterations outside are not counted.
    assert outcome.unfinished == ""
    assert outcome.final_violation <= 1e-3


def test_an_ordinary_start_spends_no_iteration_outside(tmp_path):
    outcome = run_exploration(job(tmp_path, x0=0.05))
    assert outcome.saturation == pytest.approx(0.15)
    assert outcome.exit_iterations == 0
    assert outcome.iterations == 3


@pytest.mark.parametrize(
    "limits",
    [{"exit_iterations": 1}, {"exit_seconds": 0.0}],
    ids=["iterations", "seconds"],
)
def test_an_exploration_stuck_outside_is_ended_and_says_so(tmp_path, limits):
    work = job(tmp_path, x0=0.5, factory=outside_scenario, iterations=20)
    outcome = run_exploration(replace(work, **limits))
    assert outcome.error == ""
    assert "still outside the feasible domain" in outcome.unfinished
    assert outcome.exit_iterations >= 1
    assert outcome.iterations == 0


class FromTheMiddle(Done):
    """An exploration started where the problem starts, outside its domain."""

    def __init__(self, job, threads, timeout):
        super().__init__(replace(job, x0=[0.5] * SIZE), threads, timeout)


class Exploring1(FakeBackend):
    """Explores at its first call, and keeps the contexts it is given."""

    def __init__(self):
        super().__init__([], then=FINE)
        self.explored = False
        self.contexts = []

    def send(self, request):
        context = json.loads(request.messages[0].text)
        self.contexts.append(context)
        if self.explored or context["trigger"] == "exploration":
            return super().send(request)
        self.explored = True
        action = {
            "kind": "explore",
            "iterations": 10,
            "starts": [
                {
                    "label": "far",
                    "why": "Another zone.",
                    "perturb": {"scale": 0.5, "seed": 1},
                }
            ],
        }
        self._then = FakeBackend.decision({"diagnosis": "d", "action": action})
        try:
            return super().send(request)
        finally:
            self._then = FINE


def test_claude_reads_what_a_start_outside_the_domain_did(tmp_path):
    backend = Exploring1()
    pilot = ClaudePilot(
        mode="pilot",
        backend=backend,
        triggers=TriggerSettings(
            period=None, launch_pause=0.0, min_interval=0, start=False, events=False
        ),
        journal=tmp_path / "journal.jsonl",
        report=False,
        exploration=ExplorationSettings(
            factory=outside_scenario,
            launch=FromTheMiddle,
            max_iterations=3,
            exit_iterations=1,
        ),
    )
    pilot.execute(outside_scenario(), "LSO_MMA", max_iter=6)
    (answer,) = [c for c in backend.contexts if c["trigger"] == "exploration"]
    (result,) = answer["pilot"]["explorations"]["results"]
    assert result["label"] == "far"
    assert result["saturation"] > 0.25
    assert result["exit_iterations"] == 1
    assert "still outside the feasible domain" in result["unfinished"]
    assert answer["pilot"]["explorations"]["made"] == 1
