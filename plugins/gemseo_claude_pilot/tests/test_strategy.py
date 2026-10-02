"""Judging decisions on the iterates, comparing strategies, restoring feasibility."""

import json
import logging
from types import SimpleNamespace

import numpy as np
import pytest
from pilot_samples import problem as problem_snapshot

pytest.importorskip("gemseo_lso.gemseo")

from test_lso_pilot import FINE
from test_lso_pilot import scenario

import gemseo_claude_pilot.pilot as pilot_module
from gemseo_claude_pilot import ClaudePilot
from gemseo_claude_pilot.backends import FakeBackend
from gemseo_claude_pilot.context import optimizer_progress
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.detectors import DetectorSettings
from gemseo_claude_pilot.detectors import detect
from gemseo_claude_pilot.guardrails import Limits
from gemseo_claude_pilot.guardrails import RejectedDecisionError
from gemseo_claude_pilot.guardrails import check
from gemseo_claude_pilot.journal import read_journal
from gemseo_claude_pilot.progress import TrialSettings
from gemseo_claude_pilot.progress import harm
from gemseo_claude_pilot.progress import merit
from gemseo_claude_pilot.progress import progress
from gemseo_claude_pilot.progress import remaining_gain
from gemseo_claude_pilot.snapshots import history_from_entries
from gemseo_claude_pilot.snapshots import iterate_entries
from gemseo_claude_pilot.triggers import Triggers
from gemseo_claude_pilot.triggers import TriggerSettings

logging.getLogger("gemseo").setLevel(logging.WARNING)
logging.getLogger("gemseo_lso").setLevel(logging.WARNING)

EVERY_ITERATION = TriggerSettings(
    period=None, launch_pause=0.0, min_interval=0, start=False
)


def reports(objectives, violations=None, kkt=0.1, first=1):
    violations = violations or [0.0] * len(objectives)
    return [
        {
            "iteration": first + index,
            "evaluation": 3 * (first + index),
            "objective": objective,
            "max_constraint": violation,
            "kkt_residual": kkt,
            "method": "mma",
        }
        for index, (objective, violation) in enumerate(
            zip(objectives, violations, strict=True)
        )
    ]


# Judging a change of settings.


def test_the_progress_of_a_window():
    measured = progress(reports([1.0, 0.9, 0.8], [0.02, 0.0, -0.1]))
    assert measured.gain == pytest.approx(0.1)  # Relative, per iteration.
    assert measured.violation == pytest.approx(0.02 / 3)
    assert progress(reports([1.0])) is None


def test_a_change_that_halves_the_gain_with_nothing_better_is_harmful():
    before = progress(reports([1.0, 0.9, 0.8, 0.7, 0.6]))
    slower = progress(reports([0.6, 0.58, 0.56, 0.54, 0.52]))
    assert "gained 3.33% per iteration instead of 10.00%" in harm(
        before, slower, TrialSettings()
    )
    # The same slowdown with a better residual pays for itself.
    settled = progress(reports([0.6, 0.58, 0.56, 0.54, 0.52], kkt=0.01))
    assert harm(before, settled, TrialSettings()) == ""
    # A run that was not descending cannot be slowed.
    flat = progress(reports([1.0] * 5))
    assert harm(flat, slower, TrialSettings()) == ""


def test_what_the_objective_may_still_gain():
    # A descent that slows down has less to gain than a steady one; a stalled
    # run gains nothing.
    slowing = [1.0 - 0.04 * i for i in range(5)]
    slowing += [0.84 - 0.02 * (i - 4) for i in range(5, 10)]
    steady = [1.0 - 0.02 * i for i in range(10)]
    estimate = remaining_gain(reports(slowing), 100)
    assert 0 < estimate.expected < remaining_gain(reports(steady), 100).expected
    assert remaining_gain(reports([1.0] * 10), 100).expected == 0.0
    assert remaining_gain(reports([1.0] * 4), 100) is None  # Two windows needed.
    context = optimizer_progress(reports(slowing), 300)
    assert context["iterations_left"] == 100
    assert context["expected_remaining_gain"] > 0


def test_a_branch_is_ranked_by_its_objective_and_its_violation():
    good = reports([1.0, 0.9, 0.8], [0.0, 0.0, 0.0])
    infeasible = reports([1.0, 0.8, 0.7], [0.0, 0.2, 0.2])
    assert merit(good, 1.0) < merit(infeasible, 1.0)
    assert merit(reports([float("nan")] * 3), 1.0) == float("inf")


# The detectors read the iterates.


def entries_of(evaluations):
    return [
        (np.array([x, 0.0]), {"f": np.array([x]), "g": np.array([-1.0])})
        for x in evaluations
    ]


def test_the_iterates_are_the_evaluations_the_reports_end_at():
    entries = entries_of([0, 1, 5, 2, 9, 3, 4])
    kept = iterate_entries(entries, [{"evaluation": 1}, {"evaluation": 4}])
    assert [float(x[0]) for x, _ in kept] == [0.0, 2.0]
    assert len(iterate_entries(entries, [])) == len(entries)  # Without reports.


def test_inner_iterations_are_not_an_oscillation():
    # The iterates go steadily one way; between them, the evaluations of the
    # inner iterations go back and forth.
    inner = []
    for iterate in range(1, 9):
        inner += [iterate + 0.5, iterate - 0.4, iterate]
    entries = entries_of(inner)
    snapshot = problem_snapshot(algo_name="LSO_MMA")
    history = history_from_entries(entries, snapshot)
    last = [{"evaluation": 3 * (i + 1)} for i in range(8)]
    iterates = history_from_entries(iterate_entries(entries, last), snapshot)
    settings = DetectorSettings(oscillation_window=6)
    kinds = [event.kind for event in detect(history, snapshot, settings)]
    assert "oscillation" in kinds  # The evaluations seem to oscillate...
    kinds = [
        event.kind for event in detect(history, snapshot, settings, iterates=iterates)
    ]
    assert "oscillation" not in kinds  # ...the iterates do not.


# The guardrails of the new actions.


def lso_problem(max_constraint=0.05, **settings):
    state = tuple(
        {
            "iteration": i,
            "evaluation": 3 * i,
            "objective": 1.0,
            "max_constraint": max_constraint,
            "kkt_residual": 0.1,
        }
        for i in range(1, 6)
    )
    return problem_snapshot(
        algo_name="LSO_MMA",
        evaluation_budget=600,
        algorithm_state=state,
        settings={"move_limit": 0.2},
        **settings,
    )


def decision(action):
    return Decision.model_validate({"diagnosis": "d", "action": action})


COMPARE = {
    "kind": "compare",
    "iterations": 4,
    "options": [{"label": "small", "settings": {"move_limit": 0.05}}],
}


def test_a_comparison_within_the_limits_is_accepted():
    snapshot = lso_problem()
    checked = check(decision(COMPARE), snapshot, Limits.of(snapshot), 15)
    assert checked.decision.action.kind == "compare"


@pytest.mark.parametrize(
    ("action", "comparisons", "message"),
    [
        ({**COMPARE, "iterations": 10}, 0, "more than 50%"),
        (COMPARE, 2, "2 comparisons of this run are used"),
        (
            {**COMPARE, "options": [{"label": "o", "settings": {"max_iter": 5}}]},
            0,
            "set by the comparison",
        ),
    ],
)
def test_a_comparison_beyond_the_limits_is_refused(action, comparisons, message):
    snapshot = lso_problem()
    with pytest.raises(RejectedDecisionError, match=message):
        check(
            decision(action),
            snapshot,
            Limits.of(snapshot),
            500,
            comparisons=comparisons,
        )


def test_the_new_actions_need_the_large_scale_optimizer():
    snapshot = problem_snapshot(algo_name="SLSQP", evaluation_budget=600)
    with pytest.raises(RejectedDecisionError, match="applies to LSO_MMA and LSO_GCMMA"):
        check(decision(COMPARE), snapshot, Limits.of(snapshot), 5)
    with pytest.raises(RejectedDecisionError, match="applies to LSO_MMA"):
        check(
            decision({"kind": "restore_feasibility"}), snapshot, Limits.of(snapshot), 5
        )


def test_there_is_nothing_to_restore_when_the_iterate_is_feasible():
    feasible = lso_problem(max_constraint=-0.1)
    with pytest.raises(RejectedDecisionError, match="nothing to restore"):
        check(
            decision({"kind": "restore_feasibility"}), feasible, Limits.of(feasible), 5
        )
    violated = lso_problem()
    check(decision({"kind": "restore_feasibility"}), violated, Limits.of(violated), 5)


# The pilot.


def run(actions, tmp_path, max_iter=40, start=0.5, **options):
    """A run with Claude deciding ``actions`` at its first calls, then nothing."""
    answers = [
        FakeBackend.decision({"diagnosis": "d", "action": action, "rationale": "r"})
        if action
        else FINE
        for action in actions
    ]
    path = tmp_path / "journal.jsonl"
    options.setdefault("triggers", EVERY_ITERATION)
    pilot = ClaudePilot(
        mode="pilot",
        backend=FakeBackend(answers, then=FINE),
        journal=path,
        report=False,
        **options,
    )
    study = scenario()
    study.formulation.optimization_problem.design_space.set_current_value(
        np.full(60, start)
    )
    result = pilot.execute(study, "LSO_MMA", max_iter=max_iter)
    return result, list(read_journal(path)), pilot


def of_kind(journal, kind):
    return [record for record in journal if record["kind"] == kind]


def test_strategies_are_compared_from_the_same_state(tmp_path):
    action = {
        "kind": "compare",
        "iterations": 3,
        "options": [
            {"label": "small moves", "settings": {"move_limit": 0.05}},
            {"label": "gcmma", "algo_name": "LSO_GCMMA"},
        ],
    }
    result, journal, _ = run([None, None, action], tmp_path, max_iter=60)
    (comparison,) = of_kind(journal, "comparison")
    labels = [branch["label"] for branch in comparison["branches"]]
    assert labels == ["current strategy", "small moves", "gcmma"]
    assert comparison["kept"] in labels
    # One segment for the run, one for each branch, one for what goes on.
    reasons = [segment.reason for segment in result.segments]
    assert sum("a branch of a comparison" in reason for reason in reasons) == 3
    # Each branch starts where the others do: the iteration after the state.
    branches = [
        [
            r["iteration"]
            for r in of_kind(journal, "algorithm")
            if r.get("branch") == label
        ]
        for label in labels
    ]
    assert all(iterations == [4, 5, 6] for iterations in branches)
    # The run goes on from the branch kept: its numbering, one iteration at a time.
    numbers = [
        r["iteration"] for r in of_kind(journal, "algorithm") if "branch" not in r
    ]
    assert numbers[:3] == [1, 2, 3]
    assert numbers[3] == 7
    assert numbers == sorted(numbers)
    # Claude learns what happened to its decision.
    assert any("kept" in outcome for outcome in outcomes(journal))


def outcomes(journal):
    """What Claude was told became of its decisions, at its last call."""
    last = json.loads(of_kind(journal, "call")[-1]["context"])
    return [item["outcome"] for item in last["decisions"]]


def test_a_change_that_slows_the_run_is_undone(tmp_path, monkeypatch):
    # A trial that judges any slowdown harmful, within two iterations.
    monkeypatch.setattr(
        pilot_module, "TRIAL", TrialSettings(window=2, slowdown=10.0, improvement=0.0)
    )
    action = {"kind": "change_settings", "settings": {"move_limit": 0.05}}
    _, journal, _ = run([None, None, action], tmp_path, max_iter=12)
    (rollback,) = of_kind(journal, "rollback")
    assert "gained" in rollback["reason"]
    assert any(outcome.startswith("Undone") for outcome in outcomes(journal))


def a_run(reports_, trial=None, evaluations=200):
    """The state of a piloted run that has made some outer iterations."""
    run = object.__new__(pilot_module._Run)
    run.reports = reports_
    run.trial = trial
    run.budget = 600
    run.problem = SimpleNamespace(database=[None] * evaluations)
    return run


STOP = decision({"kind": "stop", "reason": "converged"})


def test_a_stop_for_convergence_is_refused_while_the_objective_falls():
    falling = reports([1.0 - 0.02 * i for i in range(10)])
    refusal = a_run(falling)._stop_refusal(STOP)
    assert "still expected to gain" in refusal
    flat = reports([1.0] * 10)
    assert a_run(flat)._stop_refusal(STOP) == ""
    # Another reason is not a claim of convergence.
    hopeless = decision({"kind": "stop", "reason": "hopeless"})
    assert a_run(falling)._stop_refusal(hopeless) == ""


def test_a_stop_is_refused_until_the_last_change_is_judged():
    trial = SimpleNamespace(iteration=7)
    refusal = a_run(reports([1.0] * 10), trial=trial)._stop_refusal(STOP)
    assert "after iteration 7 is not judged yet" in refusal


def test_a_refused_stop_does_not_end_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot_module, "TRIAL", TrialSettings(window=2))
    change = {"kind": "change_settings", "settings": {"move_limit": 0.1}}
    stop = {"kind": "stop", "reason": "converged"}
    result, journal, _ = run([None, None, change, stop], tmp_path, max_iter=10)
    refused = [r for r in of_kind(journal, "status") if r.get("state") == "refused"]
    assert any("not judged yet" in r["reason"] for r in refused)
    assert result.stop_reason != "stopped by Claude"
    assert any("Refused" in outcome for outcome in outcomes(journal))


def test_feasibility_is_restored_when_claude_asks(tmp_path):
    result, journal, _ = run(
        [{"kind": "restore_feasibility"}], tmp_path, max_iter=12, start=0.0
    )
    (decided,) = of_kind(journal, "decision")
    assert decided["live"] is True
    assert len(result.segments) == 1  # Applied live, without a new segment.
    restored = [r for r in of_kind(journal, "algorithm") if r["restoration"] > 0]
    assert restored


class Scripted(FakeBackend):
    """Compares strategies at the first periodic call, switches at the end call."""

    def __init__(self):
        super().__init__([], then=FINE)
        self.compared = False

    def send(self, request):
        trigger = json.loads(request.messages[0].text)["trigger"]
        action = None
        if trigger == "periodic" and not self.compared:
            self.compared = True
            action = {
                "kind": "compare",
                "iterations": 3,
                "options": [{"label": "small", "settings": {"move_limit": 0.05}}],
            }
        elif trigger == "end":
            # Not live (ftol_rel): a new segment, after segments ended by the pilot.
            action = {
                "kind": "switch_algorithm",
                "algo_name": "LSO_GCMMA",
                "settings": {"max_iter": 9, "ftol_rel": 1e-6},
            }
        if action is None:
            return super().send(request)
        self._then = FakeBackend.decision({"diagnosis": "d", "action": action})
        try:
            return super().send(request)
        finally:
            self._then = FINE


def test_a_segment_follows_segments_ended_by_the_pilot(tmp_path):
    pilot = ClaudePilot(
        mode="pilot",
        backend=Scripted(),
        triggers=TriggerSettings(
            period=None,
            first_iteration=False,
            launch_pause=None,
            period_iterations=2,
            min_interval=0,
            events=False,
            start=False,
        ),
        journal=tmp_path / "journal.jsonl",
        report=False,
    )
    result = pilot.execute(scenario(), "LSO_MMA", max_iter=24, ftol_rel=3e-2)
    algorithms = [segment.algo_name for segment in result.segments]
    assert algorithms[-1] == "LSO_GCMMA"  # The last one ran, after the branches.
    assert result.segments[-1].ended == "completed"


# The rhythm of the consultations, chosen by Claude.


def test_claude_chooses_in_how_many_iterations_it_is_consulted_again():
    settings = TriggerSettings(period=None, min_interval=0, launch_pause=None)
    triggers = Triggers(settings)
    assert triggers.due(30, [], iteration=10)[0] == "periodic"  # The default: 10.
    triggers.set_review(3)
    assert triggers.review == 3
    assert triggers.due(33, [], iteration=12)[0] is None
    assert triggers.due(36, [], iteration=13)[0] == "periodic"
    triggers.set_review(None)
    assert triggers.due(60, [], iteration=20)[0] is None  # The default again: 10.


def test_a_review_has_a_ceiling_in_seconds():
    now = [0.0]
    settings = TriggerSettings(
        period=None, min_interval=0, first_iteration=False, review_ceiling=100.0
    )
    triggers = Triggers(settings, clock=lambda: now[0])
    triggers.set_review(40)
    assert triggers.due(3, [], iteration=1)[0] == "periodic"  # Never launched.
    now[0] = 99.0
    assert triggers.due(6, [], iteration=2)[0] is None
    now[0] = 100.0
    assert triggers.due(9, [], iteration=3)[0] == "periodic"


def test_the_review_is_bounded_by_the_pilot():
    run = a_run(reports([1.0] * 4), evaluations=500)  # 100 evaluations left.
    run.pilot = SimpleNamespace(
        adaptive_review=True, journal=SimpleNamespace(write=lambda *a, **k: None)
    )
    run.advisor = SimpleNamespace(triggers=Triggers(TriggerSettings()))
    run.reports[-1]["evaluation"] = 12  # Three evaluations an iteration.
    run._set_review(100)
    assert run.advisor.triggers.review == 16  # Half of the 33 iterations left.
    run._set_review(0 + 1)
    assert run.advisor.triggers.review == 1
    run.pilot.adaptive_review = False
    run._set_review(5)
    assert run.advisor.triggers.review == 1  # Not adaptive: Claude is not heard.


def test_the_time_of_an_iteration_and_of_a_call_are_given_to_claude():
    rows = [
        {**row, "model_time": 3.0, "optimizer_time": 1.0}
        for row in reports([1.0, 0.9, 0.8])
    ]
    run = a_run(rows)
    run.advisor = SimpleNamespace(
        latencies=[40.0, 20.0, 30.0], triggers=Triggers(TriggerSettings())
    )
    timing = run._timing()
    assert timing["seconds_per_iteration"] == 4.0
    assert timing["seconds_per_call"] == 30.0
    # 30 s of call, 25 % of the time of the run: 30 / (0.25 * 4) iterations.
    assert timing["suggested_review_in"] == 25  # Capped.
    run.advisor.latencies = [2.0]
    assert run._timing()["suggested_review_in"] == 2


def test_claude_sets_its_rhythm_in_a_run(tmp_path):
    action = {"kind": "none"}
    answers = [
        FakeBackend.decision({"diagnosis": "d", "action": action, "review_in": 4}),
    ]
    path = tmp_path / "journal.jsonl"
    pilot = ClaudePilot(
        mode="pilot",
        backend=FakeBackend(answers, then=FINE),
        triggers=TriggerSettings(period=None, min_interval=0, start=False),
        journal=path,
        report=False,
    )
    pilot.execute(scenario(), "LSO_MMA", max_iter=14)
    journal = list(read_journal(path))
    (review,) = of_kind(journal, "review")
    # Bounded by half of the iterations left: few, so early in a short run.
    assert review["requested"] == 4
    assert 1 <= review["iterations"] <= 4
    context = json.loads(of_kind(journal, "call")[0]["context"])
    assert {"seconds_per_iteration"} <= set(context["pilot"]["timing"])


# A stop waits for feasibility; one change at a time.


def test_a_stop_brings_the_iterate_back_within_the_constraints(tmp_path):
    stop = {"kind": "stop", "reason": "hopeless"}
    result, journal, _ = run([stop], tmp_path, max_iter=40, start=0.0)
    assert result.stop_reason == "stopped by Claude"
    assert len(result.segments) == 1  # Applied live.
    last = of_kind(journal, "algorithm")[-1]
    assert last["max_constraint"] <= 1e-3  # Ends feasible.
    assert len(of_kind(journal, "algorithm")) > 1  # After a few more iterations.


def test_a_second_change_is_refused_until_the_first_is_judged(tmp_path):
    first = {"kind": "change_settings", "settings": {"move_limit": 0.1}}
    second = {"kind": "change_settings", "settings": {"screening_margin": 0.4}}
    _, journal, _ = run([None, None, first, second], tmp_path, max_iter=8)
    refused = [r for r in of_kind(journal, "status") if r.get("state") == "refused"]
    assert any("one change at a time" in r["reason"] for r in refused)
    assert len(of_kind(journal, "decision")) == 1
