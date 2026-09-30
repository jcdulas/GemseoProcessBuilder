import io
import json

import pytest
from pilot_samples import sellar

from gemseo_claude_pilot.backends import FakeBackend
from gemseo_claude_pilot.journal import Journal
from gemseo_claude_pilot.journal import read_journal
from gemseo_claude_pilot.session import SessionError
from gemseo_claude_pilot.session import ask
from gemseo_claude_pilot.session import main
from gemseo_claude_pilot.session import review

SCRIPT = """
from gemseo import create_design_space, create_discipline, create_scenario


def build_scenario():
    print("Printed by the script.")
    discipline = create_discipline(
        "AnalyticDiscipline", expressions={"f": "(x - 1)**2 + y**2"}, name="Bowl"
    )
    space = create_design_space()
    space.add_variable("x", lower_bound=-2.0, upper_bound=2.0, value=0.0)
    space.add_variable("y", lower_bound=-2.0, upper_bound=2.0, value=1.0)
    return create_scenario([discipline], "f", space, formulation_name="DisciplinaryOpt")
"""


@pytest.fixture
def finished_run(tmp_path):
    """The folder of a finished run of Sellar, piloted in Advisor mode."""
    sellar().save_optimization_history(tmp_path / "history.h5")
    journal = Journal(tmp_path / "copilot" / "journal.jsonl")
    journal.write(
        "status",
        state="started",
        mode="advisor",
        algo_name="SLSQP",
        settings={"max_iter": 5},
        budget=5,
        data_level="no_code",
    )
    journal.write(
        "decision",
        decision={
            "diagnosis": "Slow.",
            "action": {"kind": "stop", "reason": "converged"},
        },
    )
    return tmp_path


def test_a_question_on_a_finished_run(finished_run):
    backend = FakeBackend([FakeBackend.text("Yes: c_1 is active at the optimum.")])
    answer = ask(finished_run, "Is it converged?", backend=backend)
    assert answer["ok"]
    assert answer["text"] == "Yes: c_1 is active at the optimum."
    (request,) = backend.requests
    context = json.loads(request.messages[0].text)
    assert (context["trigger"], context["question"]) == ("question", "Is it converged?")
    assert context["problem"]["algorithm"]["name"] == "SLSQP"
    assert context["decisions"][0]["decision"]["action"]["kind"] == "stop"
    assert context["state"]["evaluations"] > 0
    assert "submit_decision" not in [tool.name for tool in request.tools]
    kinds = [
        r["kind"] for r in read_journal(finished_run / "copilot" / "journal.jsonl")
    ]
    assert kinds[-3:] == ["user", "call", "answer"]


def test_a_run_without_history(tmp_path):
    with pytest.raises(SessionError, match="no history"):
        ask(tmp_path, "Why?", backend=FakeBackend([]))


def test_a_review_before_the_run(tmp_path, capsys):
    script = tmp_path / "study.py"
    script.write_text(SCRIPT, encoding="utf-8")
    backend = FakeBackend([FakeBackend.text("Start closer to x = 1.")])
    answer = review(script, "SLSQP", {"max_iter": 20}, 20, backend=backend)
    assert answer["text"] == "Start closer to x = 1."
    context = json.loads(backend.requests[0].messages[0].text)
    assert context["trigger"] == "start"
    assert context["question"].startswith("Review this optimization")
    assert context["state"]["evaluations"] == 0
    assert [v["name"] for v in context["problem"]["design_variables"]] == ["x", "y"]


def test_the_process_answers_on_its_output():
    output = io.StringIO()
    request = json.dumps(
        {"command": "review", "script": "missing.py", "algo_name": "SLSQP"}
    )
    assert main(io.StringIO(request), output) == 1
    answer = json.loads(output.getvalue())
    assert answer["ok"] is False
    assert "off" in answer["error"] or "missing.py" in answer["error"]
