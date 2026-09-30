import json

import pytest
from pilot_samples import sellar

from gemseo_claude_pilot.backends import ToolCall
from gemseo_claude_pilot.privacy import Anonymizer
from gemseo_claude_pilot.snapshots import Component
from gemseo_claude_pilot.snapshots import database_entries
from gemseo_claude_pilot.snapshots import history_from_entries
from gemseo_claude_pilot.snapshots import snapshot_problem
from gemseo_claude_pilot.tools import MAX_ROWS
from gemseo_claude_pilot.tools import ToolAnswers

COMPONENT = Component("Sellar1", "The first discipline.", ("x_1",), ("y_1",), "SRC")


def answers(level="no_code"):
    problem = sellar().formulation.optimization_problem
    snapshot = snapshot_problem(
        problem, "SLSQP", 100, {"max_iter": 5}, components=(COMPONENT,)
    )
    entries = database_entries(problem)
    history = history_from_entries(entries, snapshot)
    anonymizer = Anonymizer(snapshot) if level == "anonymized" else None
    return ToolAnswers(snapshot, history, entries, level, anonymizer), history


def ask(tool_answers, tool, **arguments):
    return json.loads(tool_answers(ToolCall("call_0", tool, arguments)))


def test_iterations():
    tool_answers, history = answers()
    answer = ask(
        tool_answers, "get_iterations", first=1, last=2, variables=["x_shared"]
    )
    rows = answer["evaluations"]
    assert [row["evaluation"] for row in rows] == [1, 2]
    assert rows[0]["objective"] == pytest.approx(history.objective[1], rel=1e-5)
    assert set(rows[0]["constraints"]) == {"c_1", "c_2"}
    assert len(rows[0]["variables"]["x_shared"]) == 2
    assert answer["truncated"] is False
    assert (
        len(ask(tool_answers, "get_iterations", first=0, last=10**6)["evaluations"])
        <= MAX_ROWS
    )


def test_variable():
    tool_answers, history = answers()
    answer = ask(tool_answers, "get_variable", name="x_shared", components=[1])
    assert answer["components"] == [1]
    assert answer["upper"] == [10.0]
    assert len(answer["history"]) == history.n_evaluations
    assert len(answer["objective_gradient_at_best"]) == 1


def test_constraint():
    tool_answers, history = answers()
    answer = ask(tool_answers, "get_constraint", name="c_1")
    assert answer["type"] == "ineq"
    assert answer["state_at_best"] in {"active", "inactive", "violated"}
    assert len(answer["history"]) == history.n_evaluations


def test_algorithms():
    tool_answers, _ = answers()
    names = [item["name"] for item in ask(tool_answers, "list_algorithms")]
    assert "SLSQP" in names
    assert "L-BFGS-B" not in names  # No constraints.
    settings = ask(tool_answers, "get_algorithm_settings", name="SLSQP")
    assert "ftol_rel" in settings["settings"]
    assert "use_database" not in settings["settings"]
    assert settings["current"] == {"max_iter": 5}


def test_component_by_level():
    no_code, _ = answers()
    assert "source" not in ask(no_code, "get_component", name="Sellar1")
    full, _ = answers("full")
    assert ask(full, "get_component", name="Sellar1")["source"] == "SRC"
    anonymized, _ = answers("anonymized")
    with pytest.raises(ValueError, match="no component named Sellar1"):
        anonymized(ToolCall("call_0", "get_component", {"name": "Sellar1"}))


def test_anonymized_names_and_values():
    tool_answers, _ = answers("anonymized")
    answer = ask(tool_answers, "get_variable", name="x3")
    assert answer["upper"] == [1.0, 1.0]
    assert answer["lower"] == [0.0, 0.0]
    rows = ask(tool_answers, "get_iterations", first=0, last=0, variables=["x1"])
    assert set(rows["evaluations"][0]["constraints"]) == {"g1", "g2"}
    assert list(rows["evaluations"][0]["variables"]) == ["x1"]
    assert ask(tool_answers, "get_constraint", name="g1")["name"] == "g1"
    with pytest.raises(ValueError, match="no design variable named x_1"):
        tool_answers(ToolCall("call_0", "get_variable", {"name": "x_1"}))


def test_unknown_tool():
    tool_answers, _ = answers()
    with pytest.raises(ValueError, match="no tool named guess"):
        tool_answers(ToolCall("call_0", "guess", {}))
