"""Exploring other zones of the design space, in processes Claude does not guide."""

import json
import logging

import numpy as np
import pytest
from pilot_samples import problem as problem_snapshot
from test_lso_pilot import FINE
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
