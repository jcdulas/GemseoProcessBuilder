"""The Claude pilot and the large-scale optimizer (plan 70)."""

import logging
from collections.abc import Iterable
from collections.abc import Mapping
from typing import Any

import numpy as np
import pytest
from pilot_samples import problem as problem_snapshot

pytest.importorskip("gemseo_lso.gemseo")

from gemseo import create_design_space
from gemseo import create_scenario
from gemseo.core.discipline import Discipline

from gemseo_claude_pilot import ClaudePilot
from gemseo_claude_pilot.backends import FakeBackend
from gemseo_claude_pilot.backends.base import ToolCall
from gemseo_claude_pilot.context import TARGET_TOKENS
from gemseo_claude_pilot.context import build_context
from gemseo_claude_pilot.context import estimate_tokens
from gemseo_claude_pilot.context import render
from gemseo_claude_pilot.detectors import DetectorSettings
from gemseo_claude_pilot.detectors import algorithm_events
from gemseo_claude_pilot.journal import read_journal
from gemseo_claude_pilot.snapshots import Constraint
from gemseo_claude_pilot.snapshots import HistorySnapshot
from gemseo_claude_pilot.tools import ToolAnswers
from gemseo_claude_pilot.triggers import TriggerSettings
from gemseo_lso.benchmarks.synthetic import LocalConstraints

logging.getLogger("gemseo").setLevel(logging.WARNING)
logging.getLogger("gemseo_lso").setLevel(logging.WARNING)

SIZE = 60
FINE = FakeBackend.decision({"diagnosis": "Fine."})
EVERY_THREE = TriggerSettings(period=3, min_interval=0, check_every=1, start=False)


class Local(Discipline):
    """``f`` and the vector constraint ``g`` of the synthetic problem."""

    def __init__(self) -> None:
        super().__init__("Local")
        self.problem = LocalConstraints(SIZE, active_share=0.05, seed=1)
        x0 = self.problem.x0.copy()
        self.io.input_grammar.update_from_data({"x": x0})
        self.io.output_grammar.update_from_data({"f": np.zeros(1), "g": np.zeros(SIZE)})
        self.io.input_grammar.defaults = {"x": x0}

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        objective, constraints, _ = self.problem.values(input_data["x"])
        return {"f": np.array([objective]), "g": constraints}

    def _compute_jacobian(
        self, input_names: Iterable[str] = (), output_names: Iterable[str] = ()
    ) -> None:
        x = self.io.data["x"]
        self.jac = {
            "f": {"x": self.problem.objective_gradient(x)[None, :]},
            "g": {"x": self.problem.jacobian},
        }


def scenario():
    space = create_design_space()
    space.add_variable("x", size=SIZE, lower_bound=0.0, upper_bound=1.0, value=0.5)
    study = create_scenario([Local()], "f", space, formulation_name="DisciplinaryOpt")
    study.add_constraint("g", "ineq")
    return study


def run(action, tmp_path, algo_name="LSO_MMA"):
    decision = FakeBackend.decision(
        {"diagnosis": "d", "action": action, "rationale": "r"}
    )
    path = tmp_path / "journal.jsonl"
    pilot = ClaudePilot(
        mode="pilot",
        backend=FakeBackend([decision], then=FINE),
        triggers=EVERY_THREE,
        journal=path,
        threaded=False,
        report=False,
    )
    result = pilot.execute(scenario(), algo_name, max_iter=12)
    return result, list(read_journal(path))


def records(journal, kind):
    return [record for record in journal if record["kind"] == kind]


def test_a_live_setting_applies_without_a_new_segment(tmp_path):
    action = {
        "kind": "change_settings",
        "settings": {"screening_margin": 0.4, "screening_margin_min": 0.1},
    }
    result, journal = run(action, tmp_path)
    assert len(result.segments) == 1
    assert len(result.decisions) == 1
    (decision,) = records(journal, "decision")
    assert decision["live"] is True
    reports = records(journal, "algorithm")
    assert reports and {"working_set", "rows_computed", "evaluation"} <= set(reports[0])


def test_an_invalid_live_setting_is_refused(tmp_path):
    result, _ = run(
        {"kind": "change_settings", "settings": {"move_limit": 5.0}}, tmp_path
    )
    assert result.decisions == []
    assert len(result.segments) == 1


def test_mma_switches_to_gcmma_without_a_new_segment(tmp_path):
    result, journal = run(
        {"kind": "switch_algorithm", "algo_name": "LSO_GCMMA"}, tmp_path
    )
    assert len(result.segments) == 1
    (decision,) = records(journal, "decision")
    assert decision["live"] is True
    # MMA until the decision, GCMMA from the next outer iteration on.
    methods = [record["method"] for record in records(journal, "algorithm")]
    switched = methods.index("gcmma")
    assert set(methods[:switched]) <= {"mma"}
    assert set(methods[switched:]) == {"gcmma"}


def test_the_optimizer_waits_for_claude_at_the_end_of_an_iteration(tmp_path):
    decision = FakeBackend.decision(
        {
            "diagnosis": "d",
            "action": {"kind": "switch_algorithm", "algo_name": "LSO_GCMMA"},
            "rationale": "r",
        }
    )
    path = tmp_path / "journal.jsonl"
    pilot = ClaudePilot(
        mode="pilot",
        backend=FakeBackend([decision], then=FINE),
        # The default: the optimizer waits for Claude. A call at the end of each
        # iteration launched more than 0 s after the last one.
        triggers=TriggerSettings(
            period=None, launch_pause=0.0, min_interval=0, start=False
        ),
        journal=path,
        report=False,
    )
    pilot.execute(scenario(), "LSO_MMA", max_iter=12)
    journal = list(read_journal(path))
    kinds = [record["kind"] for record in journal]
    first = kinds.index("algorithm")
    # The iteration ends, Claude is called and answers, the strategy is applied,
    # and only then does the next iteration start.
    assert kinds[first : first + 4] == ["algorithm", "call", "answer", "decision"]
    methods = [record["method"] for record in records(journal, "algorithm")]
    assert methods[:2] == ["mma", "gcmma"]
    # One call at the end of each outer iteration.
    assert len(records(journal, "call")) == len(methods)


def test_the_context_of_a_million_constraints_stays_small():
    size = 1_000_000
    constraint = Constraint("stress", "stress", "ineq", size)
    reports = tuple(
        {
            "iteration": index,
            "method": "mma",
            "objective": 0.5,
            "max_constraint": 1e-3,
            "kkt_residual": 0.1,
            "working_set": 20_000,
            "rows_computed": 20_000,
            "rows_reused": 0,
            "screening_repairs": 0,
            "inner_iterations": 0,
            "step": 0.01,
            "restoration": 0,
            "directional_derivatives": 0,
            "asymptote_spread": [0.1, 0.5, 1.0],
        }
        for index in range(1, 301)
    )
    snapshot = problem_snapshot(
        constraints=[constraint], algo_name="LSO_MMA", algorithm_state=reports
    )
    values = np.random.default_rng(0).uniform(-1.0, -0.01, size)
    values[[5, 77]] = 0.0  # Two active components.
    history = HistorySnapshot(
        objective=np.array([2.0, 1.0]),
        violation=np.zeros(2),
        step=np.zeros(2),
        recent_x=np.full((1, 2), 0.5),
        first_x=np.full(2, 5.0),
        best_x=np.full(2, 5.0),
        constraints={"stress": np.array([0.1, 0.0])},
        best_constraints={"stress": values},
    )
    context = build_context(snapshot, history)
    assert estimate_tokens(render(context)) < TARGET_TOKENS
    summary = context["problem"]["constraints"][0]["summary_at_best"]
    assert summary["active_components"] == 2
    assert summary["largest_components"][0][0] in (5, 77)
    optimizer = context["optimizer"]
    assert optimizer["outer_iterations"] == 300
    assert len(optimizer["recent"]) == 10
    # The read tool gives slices.
    answers = ToolAnswers(snapshot, history, entries=[])
    call = ToolCall("1", "get_constraint", {"name": "stress", "components": [77, 3]})
    answer = answers(call)
    assert '"components_at_best": [77, 3]' in answer
    assert '"active"' in answer


def reports_like(count=6, **changes):
    base = {
        "objective": 0.5,
        "max_constraint": 0.0,
        "kkt_residual": 0.01,
        "working_set": 1000,
        "rows_computed": 1000,
        "rows_reused": 0,
        "screening_repairs": 0,
        "inner_iterations": 0,
        "asymptote_spread": [0.1, 0.4, 1.0],
    }
    return tuple(
        {**base, **changes, "iteration": index} for index in range(1, count + 1)
    )


@pytest.mark.parametrize(
    ("reports", "settings", "kind"),
    [
        (reports_like(screening_repairs=1), {}, "repairs"),
        (
            tuple(
                {**report, "working_set": 1000 if report["iteration"] % 2 else 300}
                for report in reports_like()
            ),
            {},
            "churn",
        ),
        (reports_like(asymptote_spread=[0.001, 0.01, 0.1]), {}, "asymptotes"),
        (reports_like(inner_iterations=6), {}, "inner_iterations"),
        (reports_like(rows_reused=50, screening_repairs=1), {}, "stale_rows"),
        (reports_like(), {"max_row_evaluations": 6500}, "row_budget"),
        (
            reports_like(
                count=12,
                at_bound=1,
                near_bound=2,
                bound_costs=[[5, 0.25, 0.007], [1, 0.4, 0.0]],
                kkt_residual=0.05,
            ),
            {},
            "frozen",
        ),
    ],
)
def test_the_detectors_of_the_optimizer(reports, settings, kind):
    snapshot = problem_snapshot(algorithm_state=reports, **{"settings": settings})
    kinds = [event.kind for event in algorithm_events(snapshot, DetectorSettings(), 9)]
    assert kind in kinds
    healthy = problem_snapshot(algorithm_state=reports_like())
    assert algorithm_events(healthy, DetectorSettings(), 9) == []


def test_a_run_still_descending_is_not_frozen():
    reports = tuple(
        {**report, "objective": 0.5 - 0.01 * report["iteration"]}
        for report in reports_like(
            count=12,
            at_bound=1,
            near_bound=2,
            bound_costs=[[5, 0.25, 0.007]],
            kkt_residual=0.05,
        )
    )
    kinds = [
        event.kind
        for event in algorithm_events(
            problem_snapshot(algorithm_state=reports), DetectorSettings(), 9
        )
    ]
    assert "frozen" not in kinds


def test_a_run_far_from_settling_is_not_frozen():
    reports = reports_like(
        at_bound=2, near_bound=2, bound_costs=[[5, 0.25, 0.0]], kkt_residual=0.5
    )
    kinds = [
        event.kind
        for event in algorithm_events(
            problem_snapshot(algorithm_state=reports), DetectorSettings(), 9
        )
    ]
    assert "frozen" not in kinds


def test_the_exit_costs_of_the_bounds_are_in_the_context():
    from gemseo_claude_pilot.context import optimizer_state

    reports = reports_like(
        at_bound=1, near_bound=1, bound_costs=[[5, 0.253456789, 0.0]]
    )
    row = optimizer_state(reports)["recent"][-1]
    assert row["at_bound"] == 1
    assert row["bound_costs"][0][0] == 5
    assert row["bound_costs"][0][1] == pytest.approx(0.2535, rel=1e-3)
