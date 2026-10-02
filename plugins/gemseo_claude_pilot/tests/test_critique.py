"""The critique of the analysis: assessment, review of heavy decisions, predictions."""

import json
import logging
from types import SimpleNamespace

import pytest
from pilot_samples import problem as problem_snapshot
from pilot_samples import variable

import gemseo_claude_pilot.pilot as pilot_module
from gemseo_claude_pilot import ClaudePilot
from gemseo_claude_pilot.backends import FakeBackend
from gemseo_claude_pilot.critique import REVIEW_MARKER
from gemseo_claude_pilot.critique import review_request
from gemseo_claude_pilot.critique import verdict
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.decisions import Prediction
from gemseo_claude_pilot.exchange import exchange
from gemseo_claude_pilot.guardrails import Limits
from gemseo_claude_pilot.guardrails import RejectedDecisionError
from gemseo_claude_pilot.guardrails import check
from gemseo_claude_pilot.journal import read_journal
from gemseo_claude_pilot.triggers import TriggerSettings

logging.getLogger("gemseo").setLevel(logging.WARNING)

ASSESSMENT = {
    "hypotheses": [
        {
            "claim": "The step limits the run.",
            "evidence_for": "The objective falls 0.1 % per iteration.",
            "evidence_against": "The violation does not oscillate.",
        }
    ],
    "weaknesses": ["Ten iterations only."],
    "alternatives": [{"action": "none", "why_not": "The gain would stay small."}],
    "prediction": {"metric": "objective", "expect": "falls", "within": 3},
}


def decision(action, **fields):
    return Decision.model_validate({"diagnosis": "d", "action": action, **fields})


def limits(**fields):
    snapshot = problem_snapshot(evaluation_budget=100)
    return snapshot, Limits(
        snapshot.variables,
        snapshot.evaluation_budget,
        require_assessment=True,
        **fields,
    )


# The assessment.


def test_an_action_needs_the_critique_of_its_analysis():
    snapshot, required = limits()
    settings = {"kind": "change_settings", "settings": {"xtol_rel": 1e-8}}
    with pytest.raises(RejectedDecisionError, match="assessment"):
        check(decision(settings), snapshot, required, 10)
    checked = check(decision(settings, assessment=ASSESSMENT), snapshot, required, 10)
    assert checked.decision.assessment.prediction.within == 3
    # Without the requirement, as before.
    check(decision(settings), snapshot, Limits.of(snapshot), 10)


def test_a_stop_needs_no_prediction_and_none_no_assessment():
    snapshot, required = limits()
    no_prediction = {**ASSESSMENT, "prediction": None}
    stop = {"kind": "stop", "reason": "converged"}
    check(decision(stop, assessment=no_prediction), snapshot, required, 10)
    check(decision({"kind": "none"}), snapshot, required, 10)
    settings = {"kind": "change_settings", "settings": {"xtol_rel": 1e-8}}
    with pytest.raises(RejectedDecisionError, match="prediction"):
        check(decision(settings, assessment=no_prediction), snapshot, required, 10)


def test_a_critique_names_what_is_against_the_hypothesis():
    bad = {**ASSESSMENT, "hypotheses": [{"claim": "c", "evidence_for": "e"}]}
    with pytest.raises(ValueError, match="evidence_against"):
        decision({"kind": "none"}, assessment=bad)


# The predictions.


@pytest.mark.parametrize(
    ("prediction", "before", "now", "held"),
    [
        ({"expect": "falls"}, 1.0, 0.9, True),
        ({"expect": "falls"}, 1.0, 1.1, False),
        ({"expect": "falls", "by": 0.05}, 1.0, 0.97, False),
        ({"expect": "rises", "by": 0.05}, 1.0, 1.2, True),
        ({"expect": "stays"}, 1.0, 1.04, True),
        ({"expect": "stays"}, 1.0, 1.3, False),
        ({"expect": "stays", "by": 0.5}, 1.0, 1.3, True),
    ],
)
def test_a_prediction_holds_or_not(prediction, before, now, held):
    result = verdict(
        Prediction(metric="objective", within=3, **prediction), before, now
    )
    assert result.held is held
    assert ("Held" if held else "Did not hold") in result.text


def test_a_violation_near_zero_is_read_against_a_floor():
    # Near 0, a change is read against 1 % of the limit, not against 0: from
    # -1e-6 to 1e-4 is a change of 1 %, to 5e-3 one of 50 %.
    stays = Prediction(metric="max_constraint", expect="stays", within=3)
    assert verdict(stays, -1e-6, 1e-4).held
    assert not verdict(stays, -1e-6, 5e-3).held


# The review of heavy decisions.


def test_the_request_for_review_gives_the_budget_left_and_the_record():
    stop = decision({"kind": "stop", "reason": "converged"})
    text = review_request(stop, 244, 80, {"made": 5, "confirmed": 2})
    assert text.startswith(REVIEW_MARKER)
    assert "244 evaluations (about 80 outer iterations)" in text
    assert "with a number" in text  # The cost of a stop.
    assert "2 held out of 5" in text


class Reviewing(FakeBackend):
    """A backend that does not confirm: the script answers the review too."""

    @staticmethod
    def _confirmation(request):
        return None


def submit(action, **fields):
    return FakeBackend.decision({"diagnosis": "d", "action": action, **fields})


def test_a_heavy_decision_is_reviewed_once_and_may_be_revised():
    stop = {"kind": "stop", "reason": "converged"}
    backend = Reviewing([submit(stop, assessment=ASSESSMENT), submit({"kind": "none"})])
    result = exchange(
        backend,
        "system",
        "model",
        "context",
        check=_accepted,
        review=lambda decision: review_request(decision, 90, None, None),
    )
    # The first answer was the stop, the review sent it back, the revision won.
    assert result.checked.decision.action.kind == "none"
    assert len(backend.requests) == 2
    assert (
        backend.requests[1]
        .messages[-1]
        .tool_results[0]
        .content.startswith(REVIEW_MARKER)
    )


def _accepted(decision):
    from gemseo_claude_pilot.guardrails import Checked

    return Checked(decision)


def test_a_confirmed_decision_takes_effect_after_one_review():
    stop = {"kind": "stop", "reason": "converged"}
    backend = FakeBackend([submit(stop, assessment=ASSESSMENT)])  # Confirms itself.
    reviews = []
    result = exchange(
        backend,
        "system",
        "model",
        "context",
        check=_accepted,
        review=lambda decision: reviews.append(decision) or REVIEW_MARKER + "...",
    )
    assert result.checked.decision.action.kind == "stop"
    assert len(reviews) == 1  # Reviewed once, not again when confirmed.


# In a run.


def reports(objectives):
    return [
        {
            "iteration": index + 1,
            "evaluation": 3 * (index + 1),
            "objective": objective,
            "max_constraint": 0.0,
            "kkt_residual": 0.1,
            "method": "mma",
        }
        for index, objective in enumerate(objectives)
    ]


def a_run(rows):
    run = object.__new__(pilot_module._Run)
    run.reports = rows
    run.forecasts = []
    run.record = {"made": 0, "confirmed": 0}
    noted = []
    run._note_outcome = lambda decision, text: noted.append(text)
    run.pilot = SimpleNamespace(
        journal=SimpleNamespace(write=lambda *args, **kwargs: None)
    )
    return run, noted


def test_a_prediction_is_read_when_it_falls_due_and_the_record_is_kept():
    run, noted = a_run(reports([1.0, 0.9]))
    held = decision(
        {"kind": "none"},
        assessment={
            **ASSESSMENT,
            "prediction": {"metric": "objective", "expect": "falls", "within": 2},
        },
    )
    run._forecast(held)
    run.reports += reports([1.0, 0.9, 0.8, 0.7])[2:]  # Iterations 3 and 4.
    run._read_forecasts()
    assert run.record == {"made": 1, "confirmed": 1}
    assert noted[0].startswith("Prediction: Held")
    wrong = decision(
        {"kind": "none"},
        assessment={
            **ASSESSMENT,
            "prediction": {"metric": "objective", "expect": "rises", "within": 1},
        },
    )
    run._forecast(wrong)
    run.reports += [{**run.reports[-1], "iteration": 5, "objective": 0.6}]
    run._read_forecasts()
    assert run.record == {"made": 2, "confirmed": 1}
    assert "Did not hold" in noted[1]


def test_a_run_gives_claude_its_record_of_predictions(tmp_path):
    from test_lso_pilot import scenario

    prediction = {"metric": "objective", "expect": "falls", "within": 1}
    first = {"diagnosis": "d", "assessment": {**ASSESSMENT, "prediction": prediction}}
    path = tmp_path / "journal.jsonl"
    pilot = ClaudePilot(
        mode="pilot",
        backend=FakeBackend(
            [FakeBackend.tool(("submit_decision", first))],
            then=submit({"kind": "none"}),
        ),
        triggers=TriggerSettings(
            period=None, launch_pause=0.0, min_interval=0, start=False
        ),
        journal=path,
        report=False,
    )
    pilot.execute(scenario(), "LSO_MMA", max_iter=8)
    journal = list(read_journal(path))
    assert [r for r in journal if r["kind"] == "forecast"]
    contexts = [json.loads(r["context"]) for r in journal if r["kind"] == "call"]
    assert contexts[-1]["pilot"]["track_record"]["made"] >= 1
    assert "Prediction:" in contexts[-1]["decisions"][0]["outcome"]


# What tells a run it settled early, and what it leaves unspent.


def saturating(count=40, size=1000):
    """Variables held at a bound early, then little left to gain: a structure fixed."""
    rows = []
    for index in range(count):
        held = min(size, int(size * min(1.0, index / 15)))
        rows.append(
            {
                "iteration": index + 1,
                "evaluation": 3 * (index + 1),
                "objective": 0.34 + 0.6 * max(0.0, 1 - index / 25) ** 2,
                "max_constraint": 0.0,
                "kkt_residual": 0.01,
                "at_bound": held,
                "near_bound": held,
                "working_set": 100,
                "rows_computed": 100,
                "rows_reused": 0,
                "screening_repairs": 0,
                "inner_iterations": 0,
            }
        )
    return rows


def test_the_saturation_says_when_the_structure_was_decided():
    from gemseo_claude_pilot.context import optimizer_saturation

    saturation = optimizer_saturation(saturating(), 1000)
    assert saturation["share_now"] == 1.0
    crossed = {item["share"]: item for item in saturation["crossed"]}
    assert crossed[0.5]["iteration"] < crossed[0.9]["iteration"] <= 15
    # A lot of the objective was still to come when half the variables froze.
    assert crossed[0.5]["gained_since"] > crossed[0.9]["gained_since"] > 0
    assert optimizer_saturation([], 1000) == {}
    assert optimizer_saturation([{"iteration": 1, "objective": 1.0}], 1000) == {}


def test_the_progress_gives_the_budget_left():
    from gemseo_claude_pilot.context import optimizer_progress

    progress = optimizer_progress(saturating(), 450, budget=600)
    assert progress["evaluations_left"] == 450
    assert progress["budget_left_share"] == 0.75


def snapshot_of(reports, budget=600, **settings):
    return problem_snapshot(
        variables=[variable("x", 1000, value=0.5)],
        algo_name="LSO_MMA",
        evaluation_budget=budget,
        algorithm_state=tuple(reports),
        settings=settings,
    )


def test_a_plateau_with_most_variables_at_a_bound_is_a_settled_run():
    from gemseo_claude_pilot.detectors import DetectorSettings
    from gemseo_claude_pilot.detectors import algorithm_events

    events = {
        event.kind: event.message
        for event in algorithm_events(snapshot_of(saturating()), DetectorSettings(), 99)
    }
    assert "plateau" in events
    assert "settled" in events
    assert "local optimum" in events["settled"]
    # 480 of the 600 evaluations are unspent: the run is told so, and of explore.
    assert "480 of the 600 evaluations (80%) are unspent" in events["plateau"]
    assert "explored" in events["settled"]


def test_a_run_that_spent_its_budget_is_not_told_it_has_much_left():
    from gemseo_claude_pilot.detectors import DetectorSettings
    from gemseo_claude_pilot.detectors import algorithm_events

    events = {
        event.kind: event.message
        for event in algorithm_events(
            snapshot_of(saturating(), budget=130), DetectorSettings(), 99
        )
    }
    assert "unspent" not in events["plateau"]  # 10 of 130 left: nothing to say.


def test_a_descending_run_is_not_settled():
    from gemseo_claude_pilot.detectors import DetectorSettings
    from gemseo_claude_pilot.detectors import algorithm_events

    rows = [
        {**row, "objective": 1.0 - 0.02 * row["iteration"]} for row in saturating(30)
    ]
    kinds = [
        event.kind
        for event in algorithm_events(snapshot_of(rows), DetectorSettings(), 99)
    ]
    assert "settled" not in kinds
