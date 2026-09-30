import pytest
from pilot_samples import rosenbrock

from gemseo_claude_pilot import Budget
from gemseo_claude_pilot import ClaudePilot
from gemseo_claude_pilot import events
from gemseo_claude_pilot.backends import FakeBackend
from gemseo_claude_pilot.triggers import TriggerSettings

FINE = FakeBackend.decision({"diagnosis": "The run is fine."})
EVERY_THREE = TriggerSettings(period=3, min_interval=0, check_every=1, start=False)


def switch(algo_name="NLOPT_COBYLA"):
    return FakeBackend.decision(
        {
            "diagnosis": f"Try {algo_name}.",
            "action": {"kind": "switch_algorithm", "algo_name": algo_name},
        }
    )


class User:
    """Receives the pilot's events and answers its proposals, as the application."""

    def __init__(self, answer=None):
        self.events = []
        self.answer = answer

    def __call__(self, kind, payload):
        self.events.append((kind, payload))
        if kind == "copilot.message" and payload["kind"] == "proposal" and self.answer:
            command = self.answer(payload)
            if command:
                events.send_command(command, {"id": payload["id"]})

    def messages(self, kind):
        return [
            p for k, p in self.events if k == "copilot.message" and p["kind"] == kind
        ]


@pytest.fixture
def user():
    listeners = []

    def connect(answer=None):
        listener = User(answer)
        events.subscribe(listener)
        listeners.append(listener)
        return listener

    yield connect
    for listener in listeners:
        events.unsubscribe(listener)
    events.take_commands()


def advisor(script, triggers=EVERY_THREE, **options):
    return ClaudePilot(
        mode=options.pop("mode", "advisor"),
        backend=FakeBackend(script, then=options.pop("then", FINE)),
        triggers=triggers,
        journal=False,
        threaded=False,
        **options,
    )


def test_an_accepted_proposal_is_applied(user):
    listener = user(lambda proposal: "copilot.accept")
    result = advisor([switch()]).execute(rosenbrock(), "SLSQP", max_iter=20)
    assert [segment.algo_name for segment in result.segments] == [
        "SLSQP",
        "NLOPT_COBYLA",
    ]
    (proposal,) = listener.messages("proposal")
    assert proposal["id"] == "p1"
    assert proposal["decision"]["action"]["algo_name"] == "NLOPT_COBYLA"
    assert listener.messages("closed")[0] == {
        "kind": "closed",
        "id": "p1",
        "how": "accepted",
    }


def test_a_rejected_proposal_is_not_applied(user):
    listener = user(lambda proposal: "copilot.reject")
    result = advisor([switch()]).execute(rosenbrock(), "SLSQP", max_iter=20)
    assert len(result.segments) == 1
    assert result.decisions == []
    assert listener.messages("closed")[0]["how"] == "rejected"


def test_a_newer_proposal_replaces_an_open_one(user):
    listener = user(
        lambda proposal: "copilot.accept" if proposal["id"] == "p2" else None
    )
    result = advisor([switch(), switch("NLOPT_MMA")]).execute(
        rosenbrock(), "SLSQP", max_iter=30
    )
    assert [closed["how"] for closed in listener.messages("closed")][:2] == [
        "replaced",
        "accepted",
    ]
    assert result.segments[1].algo_name == "NLOPT_MMA"


def test_the_mode_changes_during_the_run(user):
    user()
    events.send_command("copilot.mode", {"mode": "pilot"})
    pilot = advisor([switch()])
    result = pilot.execute(rosenbrock(), "SLSQP", max_iter=20)
    assert result.segments[1].algo_name == "NLOPT_COBYLA"
    assert {"command": "copilot.mode", "params": {"mode": "pilot"}}.items() <= next(
        record for record in pilot.journal.records if record["kind"] == "user"
    ).items()


def test_a_proposal_at_the_end_waits_for_the_answer(user):
    user(lambda proposal: "copilot.accept")
    end_only = TriggerSettings(period=None, events=False, start=False)
    result = advisor([switch()], triggers=end_only).execute(
        rosenbrock(), "SLSQP", max_iter=100, ftol_rel=1e-2
    )
    assert [segment.algo_name for segment in result.segments] == [
        "SLSQP",
        "NLOPT_COBYLA",
    ]


def test_an_unanswered_proposal_at_the_end_ends_the_run(user):
    listener = user()
    end_only = TriggerSettings(period=None, events=False, start=False)
    result = advisor([switch()], triggers=end_only, answer_timeout=0.05).execute(
        rosenbrock(), "SLSQP", max_iter=100, ftol_rel=1e-2
    )
    assert len(result.segments) == 1
    assert result.stop_reason == "completed"
    assert listener.messages("closed")[0]["how"] == "unanswered"


def test_a_stop_command_ends_the_run(user):
    user()
    events.send_command("stop")
    result = advisor([]).execute(rosenbrock(), "SLSQP", max_iter=20)
    assert result.stop_reason == "stopped by the user"


def test_events_of_a_piloted_run(user):
    listener = user()
    advisor([switch()], mode="pilot").execute(rosenbrock(), "SLSQP", max_iter=20)
    kinds = [kind for kind, _ in listener.events]
    assert kinds[0] == "copilot.status"
    assert {"copilot.segment", "copilot.usage", "copilot.summary"} <= set(kinds)
    assert listener.events[-1] == (
        "copilot.status",
        {"state": "off", "reason": listener.events[-2][1]["stop_reason"]},
    )
    (decision,) = listener.messages("decision")
    assert decision["decision"]["action"]["kind"] == "switch_algorithm"
    summary = listener.events[-2][1]
    assert len(summary["segments"]) == 2
    assert summary["calls"] >= 1


def test_a_failing_listener_does_not_stop_the_run(user):
    def broken(kind, payload):
        raise RuntimeError("broken")

    events.subscribe(broken)
    try:
        result = advisor([], mode="pilot").execute(rosenbrock(), "SLSQP", max_iter=10)
    finally:
        events.unsubscribe(broken)
    assert result.stop_reason in {"completed", "budget spent"}


def test_the_journal_folder_is_made_at_the_first_record(tmp_path):
    folder = tmp_path / "copilot"
    pilot = ClaudePilot(mode="pilot", journal=folder / "journal.jsonl")
    assert not folder.exists()
    pilot.journal.write("status", state="started")
    assert (folder / "journal.jsonl").exists()


QUIET = TriggerSettings(period=None, events=False, start=False, end=False)


def test_a_question_during_the_run(user):
    listener = user()
    events.send_command("copilot.ask", {"text": "Why SLSQP?"})
    answer = FakeBackend.text("Because the problem has gradients.")
    pilot = advisor([answer], triggers=QUIET, report=False)
    pilot.execute(rosenbrock(), "SLSQP", max_iter=10)
    (answered,) = listener.messages("answer")
    assert answered["text"] == "Because the problem has gradients."
    assert answered["question"] == "Why SLSQP?"
    call = next(record for record in pilot.journal.records if record["kind"] == "call")
    assert call["trigger"] == "question"
    assert '"question": "Why SLSQP?"' in call["context"]


def test_the_report_at_the_end(user, tmp_path):
    listener = user()
    journal = tmp_path / "copilot" / "journal.jsonl"
    report = FakeBackend.text("# The run\nIt converged.")
    backend = FakeBackend([report])
    pilot = ClaudePilot(
        mode="pilot", backend=backend, triggers=QUIET, journal=journal, threaded=False
    )
    result = pilot.execute(rosenbrock(), "SLSQP", max_iter=10)
    assert result.report == "# The run\nIt converged."
    assert (tmp_path / "copilot" / "report.md").read_text(
        "utf-8"
    ) == result.report + "\n"
    assert listener.messages("report") == [{"kind": "report", "text": result.report}]
    (request,) = backend.requests
    assert "submit_decision" not in [tool.name for tool in request.tools]
    assert '"trigger": "report"' in request.messages[0].text


def test_no_report_once_the_budget_is_spent():
    start_only = TriggerSettings(period=None, events=False, end=False)
    pilot = ClaudePilot(
        mode="pilot",
        backend=FakeBackend([], then=FINE),
        triggers=start_only,
        journal=False,
        threaded=False,
        budget=Budget(max_calls=1),
    )
    result = pilot.execute(rosenbrock(), "SLSQP", max_iter=10)
    assert result.report == ""
    assert [r["kind"] for r in pilot.journal.records].count("call") == 1


@pytest.mark.parametrize("wanted", [False, True])
def test_the_report_asked_for_once_the_run_is_over(wanted):
    asked = []

    def ask():
        asked.append(len(problem.database))
        return wanted

    scenario = rosenbrock()
    problem = scenario.formulation.optimization_problem
    backend = FakeBackend([FakeBackend.text("# The run")])
    pilot = ClaudePilot(
        mode="pilot",
        backend=backend,
        triggers=QUIET,
        journal=False,
        threaded=False,
        report=ask,
    )
    result = pilot.execute(scenario, "SLSQP", max_iter=10)
    assert asked == [len(problem.database)]  # Once, after the last evaluation.
    assert result.report == ("# The run" if wanted else "")
    assert len(backend.requests) == int(wanted)
