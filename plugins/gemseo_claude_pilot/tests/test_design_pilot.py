"""Claude reads the design and restarts from another one (plan 71)."""

import json
import logging

import numpy as np
import pytest
from design_samples import bar_view
from design_samples import plate

pytest.importorskip("gemseo_lso.gemseo")

from dataclasses import replace

from gemseo import create_design_space
from gemseo import create_scenario

from gemseo_claude_pilot import ClaudePilot
from gemseo_claude_pilot.advisor import Advisor
from gemseo_claude_pilot.advisor import Check
from gemseo_claude_pilot.backends import FakeBackend
from gemseo_claude_pilot.backends.base import ToolCall
from gemseo_claude_pilot.context import TARGET_TOKENS
from gemseo_claude_pilot.context import build_context
from gemseo_claude_pilot.context import estimate_tokens
from gemseo_claude_pilot.context import render
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.design import DesignPoint
from gemseo_claude_pilot.design import DesignView
from gemseo_claude_pilot.design import Grid
from gemseo_claude_pilot.design import check_description
from gemseo_claude_pilot.detectors import DetectorSettings
from gemseo_claude_pilot.detectors import algorithm_events
from gemseo_claude_pilot.guardrails import Limits
from gemseo_claude_pilot.guardrails import RejectedDecisionError
from gemseo_claude_pilot.guardrails import check
from gemseo_claude_pilot.journal import Journal
from gemseo_claude_pilot.journal import read_journal
from gemseo_claude_pilot.privacy import Anonymizer
from gemseo_claude_pilot.snapshots import Constraint
from gemseo_claude_pilot.snapshots import history_from_entries
from gemseo_claude_pilot.tools import ToolAnswers
from gemseo_claude_pilot.triggers import TriggerSettings
from gemseo_lso.benchmarks.topology.cases import l_bracket
from gemseo_lso.benchmarks.topology.disciplines import StressDiscipline

logging.getLogger("gemseo").setLevel(logging.WARNING)
logging.getLogger("gemseo_lso").setLevel(logging.WARNING)

FINE = FakeBackend.decision({"diagnosis": "Fine."})
ROUND_CORNER = {
    "kind": "restart",
    "answers": "The reentrant corner concentrates the stress.",
    "base": "best",
    "transforms": [
        {
            "kind": "set_region",
            "shape": "disk",
            "center": [3, 3],
            "radius": 1.0,
            "value": 0.0,
        }
    ],
}


def entries(count=3, size=48):
    """Evaluations of the plate: feasible, the objective decreasing."""
    return [
        (
            np.full(size, 1.0 - 0.1 * index),
            {"f": np.array([1.0 - 0.1 * index]), "g": np.full(size, -0.5)},
        )
        for index in range(count)
    ]


def restart(**changes):
    return Decision.model_validate(
        {"diagnosis": "d", "action": {**ROUND_CORNER, **changes}}
    )


def reports(count, kkt=0.1, max_constraint=-1.0):
    return tuple(
        {
            "iteration": index + 1,
            "method": "mma",
            "objective": 0.5,
            "max_constraint": max_constraint,
            "kkt_residual": kkt,
            "working_set": 10,
            "rows_computed": 10,
            "rows_reused": 0,
            "screening_repairs": 0,
            "inner_iterations": 0,
            "step": 0.01,
            "restoration": 0,
        }
        for index in range(count)
    )


# Guardrails.


def test_a_restart_within_the_limits_is_accepted():
    limits = Limits.of(plate())
    decision = restart()
    assert check(decision, plate(), limits, 10, design=bar_view()).decision == decision


@pytest.mark.parametrize(
    ("used", "restarts", "changes", "message"),
    [
        (10, 0, {}, "does not describe the physics"),
        (10, 3, {}, "the 3 restarts of this run are used"),
        (85, 0, {}, "15 evaluations are left, fewer than the 20"),
        (10, 0, {"base": 50}, "there is no evaluation 50"),
        (
            10,
            0,
            {
                "transforms": [
                    {"kind": "connect", "start": [0, 0], "end": [9, 9], "width": 1}
                ]
            },
            "outside the map",
        ),
    ],
)
def test_a_restart_beyond_the_limits_is_refused(used, restarts, changes, message):
    design = None if message.startswith("does not") else bar_view()
    with pytest.raises(RejectedDecisionError, match=message):
        check(
            restart(**changes),
            plate(),
            Limits.of(plate()),
            used,
            design=design,
            restarts=restarts,
        )


# Detector.


def test_a_run_stuck_far_from_convergence():
    settings = DetectorSettings()
    stuck = replace(plate(), algorithm_state=reports(25))
    assert "stuck" in [event.kind for event in algorithm_events(stuck, settings, 30)]
    decreasing = tuple(
        {**report, "kkt_residual": 0.1 * 0.8**index}
        for index, report in enumerate(reports(25))
    )
    moving = replace(plate(), algorithm_state=decreasing)
    assert "stuck" not in [
        event.kind for event in algorithm_events(moving, settings, 30)
    ]
    infeasible = replace(
        plate(), algorithm_state=reports(25, kkt=0.001, max_constraint=0.1)
    )
    events = algorithm_events(infeasible, settings, 30)
    assert any(
        event.kind == "stuck" and "violated" in event.message for event in events
    )


def test_a_stuck_run_shows_its_design_to_claude():
    backend = FakeBackend([FINE])
    journal = Journal(None)
    problem = replace(plate(), algorithm_state=reports(25))
    advisor = Advisor(
        backend,
        Limits.of(problem),
        journal,
        triggers=TriggerSettings(period=None, min_interval=0),
        threaded=False,
    )
    ratio = np.full((6, 8), 0.5)
    design = bar_view(stress_ratio=ratio)
    assert advisor.submit(
        Check(problem, entries(), {"mode": "pilot", "restarts": 0}, design=design)
    )
    assert advisor.poll() is not None
    context = json.loads(backend.requests[0].messages[0].text)
    assert context["events"][0]["kind"] == "stuck"
    detail = context["design"]["detail"]
    assert set(detail["maps"]) == {"density", "stress_ratio"}
    assert detail["indicators"]["load_path"]["loads"][0]["connected"]
    assert {tool.name for tool in backend.requests[0].tools} >= {
        "get_design_view",
        "get_design_indicators",
        "list_design_transforms",
    }
    assert [record["kind"] for record in journal.records].count("design") == 1


# Context and tools.


def bracket_view(size=125):
    """The bracket's description and synthesized fields: no finite elements."""
    topology = l_bracket(size)
    elements = topology.elements
    problem = plate()
    problem = replace(
        problem,
        variables=(
            replace(
                problem.variables[0],
                size=elements,
                lower=np.zeros(elements),
                upper=np.ones(elements),
                value=np.ones(elements),
            ),
        ),
        constraints=(Constraint("stress", "stress", "ineq", elements),),
    )
    description = check_description(topology.physical_description(), problem)
    grid = Grid(description)
    rng = np.random.default_rng(1)
    fields = {
        "density": grid.lay(rng.uniform(size=elements) ** 3),
        "stress_ratio": grid.lay(rng.uniform(0, 1.1, size=elements)),
        "strain_energy": grid.lay(rng.uniform(size=elements)),
        "design": grid.lay(rng.uniform(size=elements)),
    }
    design = DesignView(
        description,
        grid,
        np.zeros(elements),
        np.ones(elements),
        0,
        1e-4,
        {"best": DesignPoint("best", 2, fields)},
    )
    return problem, design


def test_the_context_of_a_large_bracket_stays_in_its_budget():
    problem, design = bracket_view()
    size = problem.design_size
    points = [
        (np.full(size, 1.0), {"f": np.array([1.0]), "stress": np.full(size, -0.5)})
        for _ in range(3)
    ]
    history = history_from_entries(points, problem)
    context = build_context(
        problem, history, trigger="event", design=design, design_detail=True
    )
    maps = context["design"]["detail"]["maps"]
    assert all(
        len(line) <= 40 for text in maps.values() for line in text.splitlines()[5:]
    )
    assert estimate_tokens(render(context)) < TARGET_TOKENS


def test_the_design_tools():
    problem = plate()
    history = history_from_entries(entries(), problem)
    answers = ToolAnswers(problem, history, entries(), design=bar_view())
    text = answers(ToolCall("1", "get_design_view", {"field": "density"}))
    assert "5 S...A..." in text
    evaluation = answers(
        ToolCall("2", "get_design_view", {"field": "design", "point": 2})
    )
    assert "at evaluation 2" in evaluation
    found = json.loads(answers(ToolCall("3", "get_design_indicators", {})))
    assert found["load_path"]["loads"][0]["connected"]
    transforms = json.loads(answers(ToolCall("4", "list_design_transforms", {})))
    assert transforms["map"]["rows"] == 6
    assert set(transforms["transforms"]) == {
        "binarize",
        "smooth",
        "set_region",
        "connect",
        "blend",
    }


def test_the_design_whatever_the_data_level():
    problem = plate()
    history = history_from_entries(entries(), problem)
    anonymizer = Anonymizer(problem)
    context = build_context(
        problem,
        history,
        level="anonymized",
        anonymizer=anonymizer,
        design=bar_view(),
        design_detail=True,
    )
    assert "detail" in context["design"]
    answers = ToolAnswers(
        problem, history, entries(), "anonymized", anonymizer, design=bar_view()
    )
    assert "5 S...A..." in answers.design_view("density")


# A piloted run of a small bracket.


def bracket_scenario(size=10):
    topology = l_bracket(size)
    space = create_design_space()
    space.add_variable(
        "x", size=topology.elements, lower_bound=0.0, upper_bound=1.0, value=1.0
    )
    study = create_scenario(
        [StressDiscipline(topology)],
        "volume",
        space,
        formulation_name="DisciplinaryOpt",
    )
    study.add_constraint("stress", "ineq")
    return study, topology


def test_claude_restarts_the_bracket_from_a_rounded_corner(tmp_path):
    decision = FakeBackend.decision({"diagnosis": "d", "action": ROUND_CORNER})
    backend = FakeBackend([decision], then=FakeBackend.text("A fine design."))
    path = tmp_path / "journal.jsonl"
    pilot = ClaudePilot(
        mode="pilot",
        backend=backend,
        triggers=TriggerSettings(period=3, min_interval=0, check_every=1, start=False),
        journal=path,
        threaded=False,
    )
    study, topology = bracket_scenario()
    result = pilot.execute(study, "LSO_MMA", max_iter=14, move_limit=0.2)
    assert len(result.segments) >= 2
    second = result.segments[1]
    assert second.reason.startswith("restart")
    (record,) = [item for item in read_journal(path) if item["kind"] == "restart"]
    assert record["answers"] == ROUND_CORNER["answers"]
    # The corner element (row 3, column 3 of the grid) starts void.
    cells = topology.physical_description()["variable_cells"]
    corner = cells.index(3 * 10 + 3)
    database = study.formulation.optimization_problem.database
    x = database.get_x_vect(second.first_evaluation + 1)
    assert x[corner] == 0.0
    # The first context sees the optimizer's prices on the grid; a later one
    # compares the design with the one before the restart.
    first = json.loads(backend.requests[0].messages[0].text)
    assert "price:stress" in first["design"]["fields"]
    last = json.loads(backend.requests[-1].messages[0].text)
    assert last["design"]["restarts"][0]["answers"] == ROUND_CORNER["answers"]
    assert "changes_since_before" in last["design"]["restarts"][0]
    # The report ends with the final design and the restart, as maps.
    assert result.report.startswith("A fine design.")
    assert "## The design" in result.report
    assert "### Restart 1" in result.report
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert report.rstrip() == result.report.rstrip()


# Steering.


def steer(**action):
    return Decision.model_validate(
        {"diagnosis": "d", "action": {"kind": "steer", "toward": "t", **action}}
    )


def test_a_steering_within_the_limits_is_accepted():
    for action in (
        {"anticipate": {"iterations": 3, "factor": 1.5}},
        {"transforms": [{"kind": "binarize"}]},
        {"variables": [{"name": "x", "value": 0.5}]},
    ):
        decision = steer(**action)
        checked = check(decision, plate(), Limits.of(plate()), 10, design=bar_view())
        assert checked.decision == decision


@pytest.mark.parametrize(
    ("action", "design", "message"),
    [
        ({}, True, "moves nothing"),
        ({"transforms": [{"kind": "binarize"}]}, False, "no transformation"),
        (
            {"variables": [{"name": "y", "value": 1.0}]},
            True,
            "no design variable named y",
        ),
        ({"variables": [{"name": "x", "value": 2.0}]}, True, "outside its bounds"),
    ],
)
def test_a_steering_beyond_the_limits_is_refused(action, design, message):
    with pytest.raises(RejectedDecisionError, match=message):
        check(
            steer(**action),
            plate(),
            Limits.of(plate()),
            10,
            design=bar_view() if design else None,
        )


def test_claude_steers_the_bracket_live(tmp_path):
    action = {
        "kind": "steer",
        "toward": "Lighter.",
        "variables": [{"name": "x", "value": 0.6}],
    }
    decision = FakeBackend.decision({"diagnosis": "d", "action": action})
    backend = FakeBackend([FINE, decision], then=FINE)
    pilot = ClaudePilot(
        mode="pilot",
        backend=backend,
        triggers=TriggerSettings(
            period=None, launch_pause=0.0, min_interval=0, start=False
        ),
        journal=tmp_path / "journal.jsonl",
        threaded=False,
        report=False,
    )
    study, _ = bracket_scenario()
    result = pilot.execute(study, "LSO_MMA", max_iter=12, move_limit=0.2)
    assert len(result.segments) == 1  # Live: no new segment.
    assert [item.action.kind for item in result.decisions] == ["steer"]
    database = study.formulation.optimization_problem.database
    points = [database.get_x_vect(index + 1) for index in range(len(database))]
    assert any(np.allclose(point, 0.6) for point in points)
    # Where the design heads, once there are iterates enough.
    contexts = [json.loads(request.messages[0].text) for request in backend.requests]
    heading = contexts[-1]["design"]["heading"]
    assert heading["over_iterates"] >= 1
    assert "trend" in heading["trend_map"].splitlines()[0]
