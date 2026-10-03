"""A call that asks for a decision and gets a text without one is asked again."""

import json
import logging

import pytest
from test_lso_pilot import EVERY_THREE
from test_lso_pilot import FINE
from test_lso_pilot import records
from test_lso_pilot import scenario

from gemseo_claude_pilot import ClaudePilot
from gemseo_claude_pilot.advisor import DECISION_TRIGGERS
from gemseo_claude_pilot.advisor import NUDGE
from gemseo_claude_pilot.backends import FakeBackend
from gemseo_claude_pilot.backends.base import Reply
from gemseo_claude_pilot.journal import read_journal
from gemseo_claude_pilot.prompts import system_prompt
from gemseo_claude_pilot.triggers import TriggerSettings

logging.getLogger("gemseo").setLevel(logging.WARNING)
logging.getLogger("gemseo_lso").setLevel(logging.WARNING)

FAST = {"dual_solver": "lbfgsb"}
REPORT = Reply(text="# Report\n\nThe run converged. Nothing else to do.")
"""A text where a decision was asked for: the report of a run that is over."""


def run(backend, tmp_path, triggers=EVERY_THREE, max_iter=6):
    pilot = ClaudePilot(
        mode="pilot",
        backend=backend,
        triggers=triggers,
        journal=tmp_path / "journal.jsonl",
        threaded=False,
        report=False,
    )
    result = pilot.execute(scenario(), "LSO_MMA", max_iter=max_iter, **FAST)
    return result, list(read_journal(tmp_path / "journal.jsonl"))


def test_a_text_without_a_decision_is_asked_again_for_the_decision(tmp_path):
    change = FakeBackend.decision(
        {
            "diagnosis": "d",
            "action": {"kind": "change_settings", "settings": {"move_limit": 0.1}},
            "rationale": "r",
        }
    )
    backend = FakeBackend([REPORT, change], then=FINE)
    result, journal = run(backend, tmp_path)
    # The second request is the first one with what is asked of Claude added.
    first, second = backend.requests[:2]
    context = first.messages[0].text
    assert json.loads(context)["trigger"] == "periodic"
    assert second.messages[0].text == context + NUDGE
    assert [r["state"] for r in records(journal, "status") if "state" in r][1] == (
        "nudged"
    )
    # Its decision was taken, and the text it wrote is kept with it.
    assert [d.action.kind for d in result.decisions] == ["change_settings"]
    (answer,) = [r for r in records(journal, "answer")][:1]
    assert "The run converged" in answer["text"]
    assert answer["decision"]["action"]["kind"] == "change_settings"


def test_the_second_request_is_made_once_only(tmp_path):
    backend = FakeBackend([REPORT, REPORT], then=FINE)
    result, journal = run(backend, tmp_path)
    assert result.decisions == []
    first_answer = records(journal, "answer")[0]
    assert first_answer["decision"] is None
    assert len(records(journal, "status")) >= 2
    nudges = [r for r in records(journal, "status") if r.get("state") == "nudged"]
    calls = records(journal, "call")
    assert len(nudges) == 1  # The two texts were one call and its second request.
    assert len(calls) >= 2


def test_a_call_with_a_decision_is_asked_once(tmp_path):
    backend = FakeBackend([], then=FINE)
    _, journal = run(backend, tmp_path)
    assert not [r for r in records(journal, "status") if r.get("state") == "nudged"]
    assert all(
        not request.messages[0].text.endswith(NUDGE) for request in backend.requests
    )


@pytest.mark.parametrize("trigger", ["start", "question", "report"])
def test_a_text_is_an_answer_to_a_question_a_review_or_a_report(trigger):
    assert trigger not in DECISION_TRIGGERS


def test_the_end_of_a_run_asks_for_a_decision_in_the_prompt():
    prompt = system_prompt()
    assert "When the trigger is `end`" in prompt
    assert "not the report" in prompt
    assert "always end by calling `submit_decision`" in prompt


class ReportsAtTheEnd(FakeBackend):
    """Decides at every call but the first of the end of the run, where it reports."""

    def __init__(self):
        super().__init__([], then=FINE)
        self.reported = False

    def send(self, request):
        # The context is a JSON text, to which a second request adds a line.
        context, _ = json.JSONDecoder().raw_decode(request.messages[0].text)
        if context["trigger"] == "end" and not self.reported:
            self.reported = True
            self.requests.append(request)
            return REPORT
        return super().send(request)


def test_the_end_of_a_run_is_asked_again_when_it_gets_a_report(tmp_path):
    triggers = TriggerSettings(period=None, min_interval=0, start=False, end=True)
    backend = ReportsAtTheEnd()
    pilot = ClaudePilot(
        mode="pilot",
        backend=backend,
        triggers=triggers,
        journal=tmp_path / "journal.jsonl",
        threaded=False,
        report=False,
    )
    pilot.execute(scenario(), "LSO_MMA", max_iter=60, kkt_tolerance=0.5, **FAST)
    journal = list(read_journal(tmp_path / "journal.jsonl"))
    ends = [r for r in records(journal, "call") if r["trigger"] == "end"]
    assert len(ends) == 1
    nudged = [r for r in records(journal, "status") if r.get("state") == "nudged"]
    assert [r["trigger"] for r in nudged] == ["end"]
    (answer,) = [r for r in records(journal, "answer") if r["trigger"] == "end"]
    assert answer["decision"]["action"]["kind"] == "none"  # After the second request.
