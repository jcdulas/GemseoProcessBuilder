"""Relaxing the constraints that block a run, and returning to a checkpoint."""

import json
import logging
from pathlib import Path

import numpy as np
import pytest
from test_exploration import decision
from test_exploration import lso_problem
from test_lso_pilot import FINE
from test_lso_pilot import records
from test_lso_pilot import scenario

from gemseo_claude_pilot import ClaudePilot
from gemseo_claude_pilot.backends import FakeBackend
from gemseo_claude_pilot.decisions import ConstraintBatch
from gemseo_claude_pilot.guardrails import Limits
from gemseo_claude_pilot.guardrails import RejectedDecisionError
from gemseo_claude_pilot.guardrails import check
from gemseo_claude_pilot.journal import read_journal
from gemseo_claude_pilot.relaxation import Checkpoint
from gemseo_claude_pilot.relaxation import Episode
from gemseo_claude_pilot.relaxation import blocking
from gemseo_claude_pilot.relaxation import design_change
from gemseo_claude_pilot.relaxation import judge_cycle
from gemseo_claude_pilot.relaxation import prune
from gemseo_claude_pilot.relaxation import scaled_batches
from gemseo_claude_pilot.relaxation import select
from gemseo_claude_pilot.relaxation import stage_over
from gemseo_claude_pilot.triggers import TriggerSettings

logging.getLogger("gemseo").setLevel(logging.WARNING)
logging.getLogger("gemseo_lso").setLevel(logging.WARNING)

EVERY_THREE = TriggerSettings(period=3, min_interval=0, check_every=1, start=False)
EVERY_ONE = TriggerSettings(period=1, min_interval=0, check_every=1, start=False)
FAST = {"dual_solver": "lbfgsb"}
"""The dual solved by L-BFGS-B: the interior point of a small problem is slower."""

# The steps of a relaxation.


def test_the_amount_falls_by_equal_parts_down_to_zero():
    episode = Episode(amount=1.0, stages=4, stage_iterations=6)
    left, factors = [], []
    while not episode.over:
        left.append(episode.amount_left())
        factors.append(episode.factor())
        episode.stage += 1
    assert left == pytest.approx([1.0, 0.75, 0.5, 0.25])
    assert factors == pytest.approx([0.75, 2 / 3, 0.5, 0.0])
    assert episode.amount_left() == 0.0
    # The factors multiply the amount left, step by step.
    amount = 1.0
    for factor, expected in zip(factors, [0.75, 0.5, 0.25, 0.0], strict=True):
        amount *= factor
        assert amount == pytest.approx(expected)


def test_a_step_ends_when_its_iterations_are_spent_or_the_objective_settles():
    episode = Episode(amount=1.0, stages=2, stage_iterations=6, since=10)
    falling = [1.0, 0.9, 0.8]
    assert stage_over(episode, falling, 11) == ""
    assert "6 iterations are spent" in stage_over(episode, falling, 16)
    flat = [1.0, 1.0 + 1e-5, 1.0 + 2e-5]
    assert stage_over(episode, flat, 11) == ""  # Too early: a step lasts 2 at least.
    assert stage_over(episode, flat, 12) == "the objective has settled"
    assert stage_over(episode, flat[:2], 14) == ""  # Not enough iterations to tell.


def test_an_episode_is_copied_with_its_curve():
    episode = Episode(amount=1.0, stages=2, stage_iterations=6, curve=[{"a": 1}])
    other = episode.copy()
    other.curve.append({"a": 2})
    other.stage = 1
    assert episode.curve == [{"a": 1}]
    assert episode.stage == 0


# The components a batch elects.

MULTIPLIERS = {"g": np.array([0.0, 4.0, 1.0, 3.0, 0.0, 2.0])}


def test_a_batch_elects_the_largest_multipliers_those_within_a_share_or_the_indices():
    top = select(MULTIPLIERS, [ConstraintBatch(top=2)])
    assert top["g"].tolist() == [1, 3]
    share = select(MULTIPLIERS, [ConstraintBatch(share=0.5)])
    assert share["g"].tolist() == [1, 3, 5]  # At least half of the largest, 4.
    indices = select(MULTIPLIERS, [ConstraintBatch(indices=[0, 5, 99])])
    assert indices["g"].tolist() == [0, 5]  # Out of range: ignored.
    both = select(MULTIPLIERS, [ConstraintBatch(top=1), ConstraintBatch(indices=[2])])
    assert both["g"].tolist() == [1, 2]


def test_zero_multipliers_are_never_elected():
    assert select({"g": np.zeros(4)}, [ConstraintBatch(top=3)]) == {}
    assert select(MULTIPLIERS, [ConstraintBatch(top=50)])["g"].tolist() == [1, 2, 3, 5]


def test_a_batch_needs_a_known_constraint():
    with pytest.raises(ValueError, match="Unknown constraint other"):
        select(MULTIPLIERS, [ConstraintBatch(constraint="other", top=1)])
    two = {"g": np.ones(2), "h": np.ones(2)}
    with pytest.raises(ValueError, match="Unknown constraint None"):
        select(two, [ConstraintBatch(top=1)])  # Which one?


@pytest.mark.parametrize("fields", [{}, {"top": 1, "share": 0.5}, {"top": 0}])
def test_a_batch_is_chosen_in_one_way(fields):
    with pytest.raises(ValueError):
        ConstraintBatch(**fields)


# What Claude reads of the blocking.


def test_the_blocking_says_how_concentrated_it_is():
    values = np.array([0.0] * 100 + [8.0, 4.0, 2.0, 1.0] + [0.5] * 50)
    result = blocking({"g": values})["g"]
    assert result["components"] == 154
    assert result["with_multiplier"] == 54
    assert result["top"][0] == [100, 1.0]
    assert result["top"][1] == [101, 0.5]
    assert result["cumulative_share"]["10"] == pytest.approx(0.45, abs=1e-3)
    assert "1000" not in result["cumulative_share"]  # Fewer components than that.


def test_nothing_blocks_a_run_without_multipliers():
    assert blocking({"g": np.zeros(5)}) == {}


# The checkpoints.


def checkpoint(name, iteration, reason, tmp_path):
    return Checkpoint(name, iteration, 1.0, 0.0, reason, tmp_path / f"{name}.h5")


def test_the_oldest_periodic_checkpoints_go_first(tmp_path):
    checkpoints = [
        checkpoint("a", 5, "periodic", tmp_path),
        checkpoint("b", 10, "before_relax", tmp_path),
        checkpoint("c", 15, "periodic", tmp_path),
        checkpoint("d", 20, "best_feasible", tmp_path),
    ]
    dropped = prune(checkpoints, limit=3)
    assert [item.id for item in checkpoints] == ["b", "c", "d"]
    assert dropped == [tmp_path / "a.h5"]
    prune(checkpoints, limit=1)  # Only the special ones left: the oldest goes.
    assert [item.id for item in checkpoints] == ["d"]


def test_a_checkpoint_tells_claude_what_it_needs():
    item = Checkpoint("it12", 12, 0.34567891, 0.0012345, "best_feasible", Path("x"), 3)
    assert item.describe() == {
        "id": "it12",
        "iteration": 12,
        "objective": 0.345679,
        "max_constraint": 0.001234,
        "reason": "best_feasible",
        "relaxed_components": 3,
    }


# The guardrails.


RELAX = {"kind": "relax", "batches": [{"top": 10}], "amount": 0.2}
STATE = {"made": 0, "active": False, "constraints": {"g": 100}}


@pytest.fixture(name="lso")
def lso_fixture():
    return lso_problem()


def test_a_relaxation_within_the_limits_is_accepted(lso):
    check(decision(RELAX), lso, Limits.of(lso), 15, relaxation=STATE)


@pytest.mark.parametrize(
    ("action", "state", "message"),
    [
        ({**RELAX, "amount": 5.0}, STATE, "at most 1"),
        ({**RELAX, "batches": [{"top": 30}]}, STATE, "at most 20 components"),
        ({**RELAX, "batches": [{"indices": [0, 100]}]}, STATE, "numbered 0 to 99"),
        ({**RELAX, "batches": [{"constraint": "x", "top": 1}]}, STATE, "unknown"),
        (RELAX, {**STATE, "made": 2}, "relaxations of this run are used"),
        (RELAX, {**STATE, "active": True}, "under way"),
        (RELAX, {"made": 0, "constraints": {}}, "no multiplier"),
    ],
)
def test_a_relaxation_beyond_the_limits_is_refused(lso, action, state, message):
    with pytest.raises(RejectedDecisionError, match=message):
        check(decision(action), lso, Limits.of(lso), 15, relaxation=state)


def test_only_a_relaxation_under_way_is_tightened(lso):
    tighten = {"kind": "tighten", "factor": 0.5}
    with pytest.raises(RejectedDecisionError, match="no constraint is relaxed"):
        check(decision(tighten), lso, Limits.of(lso), 15, relaxation=STATE)
    check(
        decision(tighten), lso, Limits.of(lso), 15, relaxation={**STATE, "active": True}
    )


def test_only_a_saved_checkpoint_is_resumed(lso):
    resume = {"kind": "resume", "checkpoint": "it10", "settings": {"move_limit": 0.1}}
    saved = {"saved": [{"id": "it10"}], "resumes": 0}
    check(decision(resume), lso, Limits.of(lso), 15, checkpoints=saved)
    with pytest.raises(RejectedDecisionError, match="no checkpoint named it10"):
        check(decision(resume), lso, Limits.of(lso), 15, checkpoints={"saved": []})
    with pytest.raises(RejectedDecisionError, match="returns to a checkpoint are used"):
        check(
            decision(resume),
            lso,
            Limits.of(lso),
            15,
            checkpoints={**saved, "resumes": 3},
        )


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"max_iter": 5}, "cannot change on a resume"),
        ({"move_limit": 5.0}, "move_limit"),
    ],
)
def test_the_settings_of_a_resume_are_checked(lso, settings, message):
    resume = {"kind": "resume", "checkpoint": "it10", "settings": settings}
    saved = {"saved": [{"id": "it10"}], "resumes": 0}
    with pytest.raises(RejectedDecisionError, match=message):
        check(decision(resume), lso, Limits.of(lso), 15, checkpoints=saved)


# In a run.


class Scripted(FakeBackend):
    """Answers with the action a function gives from the context, else fine."""

    def __init__(self, act):
        super().__init__([], then=FINE)
        self.act = act
        self.contexts = []

    def send(self, request):
        context = json.loads(request.messages[0].text)
        self.contexts.append(context)
        action = self.act(context)
        if action is None:
            return super().send(request)
        self._then = FakeBackend.decision({"diagnosis": "d", "action": action})
        try:
            return super().send(request)
        finally:
            self._then = FINE


def piloted(backend, tmp_path, triggers=EVERY_THREE):
    return ClaudePilot(
        mode="pilot",
        backend=backend,
        triggers=triggers,
        journal=tmp_path / "journal.jsonl",
        threaded=False,
        report=False,
    )


def relaxation_events(journal):
    return [
        (record["event"], record.get("amount"))
        for record in records(journal, "relaxation")
    ]


def test_claude_relaxes_the_blocking_constraints_which_come_back_by_steps(tmp_path):
    asked = []

    def act(context):
        relaxation = context["pilot"].get("relaxation", {})
        if asked or not relaxation.get("blocking"):
            return None
        asked.append(relaxation["blocking"]["g"]["top"])
        return {
            "kind": "relax",
            "batches": [{"top": 4}],
            "amount": 0.2,
            "stages": 2,
            "stage_iterations": 2,
        }

    backend = Scripted(act)
    path = tmp_path / "journal.jsonl"
    result = piloted(backend, tmp_path).execute(
        scenario(), "LSO_MMA", max_iter=14, **FAST
    )
    journal = list(read_journal(path))
    assert [d.action.kind for d in result.decisions] == ["relax"]
    # It saw the components and their multipliers before choosing.
    assert asked[0] and len(asked[0][0]) == 2
    events = relaxation_events(journal)
    assert [name for name, _ in events] == ["start", "step", "step", "end"]
    assert len(result.segments) == 1  # Live: no new segment.
    relaxed = [record["relaxed"] for record in records(journal, "algorithm")]
    assert max(relaxed) == 4
    assert relaxed[-1] == 0  # Back to the original constraints.
    (end,) = [r for r in records(journal, "relaxation") if r["event"] == "end"]
    assert [point["amount"] for point in end["curve"]] == pytest.approx([0.2, 0.1])
    # A checkpoint before the relaxation was saved.
    assert "before_relax" in [r["reason"] for r in records(journal, "checkpoint")]


def test_claude_reads_the_relaxation_under_way(tmp_path):
    def act(context):
        relaxation = context["pilot"].get("relaxation", {})
        if relaxation.get("made") or not relaxation.get("blocking"):
            return None
        return {
            "kind": "relax",
            "batches": [{"top": 3}],
            "amount": 0.3,
            "stages": 3,
            "stage_iterations": 2,
        }

    backend = Scripted(act)
    piloted(backend, tmp_path).execute(scenario(), "LSO_MMA", max_iter=14, **FAST)
    during = [
        context["pilot"]["relaxation"]
        for context in backend.contexts
        if context["pilot"].get("relaxation", {}).get("active")
    ]
    assert during
    first = during[0]["under_way"]
    assert first["components"] == 3
    assert first["of"] == 3
    assert first["amount"] == pytest.approx(0.3)
    assert 0 < first["amount_left"] <= 0.3
    assert "blocking" not in during[0]  # Not while a relaxation is under way.


def test_claude_can_tighten_a_relaxation_at_once(tmp_path):
    state = {"relaxed": False, "tightened": False}

    def act(context):
        relaxation = context["pilot"].get("relaxation", {})
        if not state["relaxed"] and relaxation.get("blocking"):
            state["relaxed"] = True
            return {"kind": "relax", "batches": [{"top": 3}], "amount": 0.3}
        if state["relaxed"] and relaxation.get("active") and not state["tightened"]:
            state["tightened"] = True
            return {"kind": "tighten", "factor": 0.0}
        return None

    path = tmp_path / "journal.jsonl"
    result = piloted(Scripted(act), tmp_path).execute(
        scenario(), "LSO_MMA", max_iter=14, **FAST
    )
    journal = list(read_journal(path))
    assert [d.action.kind for d in result.decisions] == ["relax", "tighten"]
    assert records(journal, "algorithm")[-1]["relaxed"] == 0
    assert [name for name, _ in relaxation_events(journal)][-1] == "end"


def test_the_pilot_saves_checkpoints_and_claude_returns_to_one(tmp_path):
    state = {"resumed": False}

    def act(context):
        saved = context["pilot"].get("checkpoints", {}).get("saved", [])
        if state["resumed"] or len(saved) < 3:
            return None
        state["resumed"] = True
        state["target"] = saved[0]
        return {
            "kind": "resume",
            "checkpoint": saved[0]["id"],
            "settings": {"move_limit": 0.1},
        }

    path = tmp_path / "journal.jsonl"
    backend = Scripted(act)
    result = piloted(backend, tmp_path).execute(
        scenario(), "LSO_MMA", max_iter=20, **FAST
    )
    journal = list(read_journal(path))
    assert [d.action.kind for d in result.decisions] == ["resume"]
    (resume,) = records(journal, "resume")
    target = state["target"]
    assert resume["checkpoint"] == target["id"]
    assert resume["iteration"] == target["iteration"]
    # The run went on from there: the iteration after the checkpoint came twice.
    iterations = [record["iteration"] for record in records(journal, "algorithm")]
    assert iterations.count(target["iteration"] + 1) == 2
    assert len(result.segments) >= 2
    # What came after the checkpoint left the history Claude reads.
    after = [
        context
        for context in backend.contexts
        if context["pilot"].get("checkpoints", {}).get("resumes") == 1
    ]
    assert after
    assert all(
        item["iteration"] <= target["iteration"] + 3
        for item in after[0]["pilot"]["checkpoints"]["saved"]
    )


def test_the_checkpoints_are_limited_in_number(tmp_path):
    backend = Scripted(lambda context: None)
    piloted(backend, tmp_path, EVERY_ONE).execute(
        scenario(), "LSO_MMA", max_iter=12, **FAST
    )
    sizes = [
        len(context["pilot"]["checkpoints"]["saved"])
        for context in backend.contexts
        if "checkpoints" in context["pilot"]
    ]
    assert max(sizes) <= 8


def test_a_run_that_converges_on_the_relaxed_problem_goes_on_by_segments(tmp_path):
    state = {"relaxed": False}

    def act(context):
        relaxation = context["pilot"].get("relaxation", {})
        if state["relaxed"] or not relaxation.get("blocking"):
            return None
        state["relaxed"] = True
        return {
            "kind": "relax",
            "batches": [{"top": 4}],
            "amount": 0.2,
            "stages": 2,
            "stage_iterations": 20,
        }

    path = tmp_path / "journal.jsonl"
    # A loose KKT tolerance: each step converges before the objective settles.
    result = piloted(Scripted(act), tmp_path, EVERY_ONE).execute(
        scenario(), "LSO_MMA", max_iter=200, kkt_tolerance=0.5, **FAST
    )
    journal = list(read_journal(path))
    assert state["relaxed"]
    assert [d.action.kind for d in result.decisions] == ["relax"]
    assert len(result.segments) >= 3  # The run, then a segment per step.
    events = [name for name, _ in relaxation_events(journal)]
    assert events == ["start", "step", "step", "end"]
    reports = records(journal, "algorithm")
    assert max(record["relaxed"] for record in reports) == 4
    assert reports[-1]["relaxed"] == 0
    assert result.stop_reason == "completed"


# The pump: cycles of relaxing and bringing back.


def test_the_amplitude_of_a_pump_follows_how_each_cycle_ended():
    episode = Episode(amount=0.8, stages=2, stage_iterations=4, cycles=3)
    episode.decay, episode.grow = 0.5, 2.0
    assert episode.pumping
    # A cycle that ended where it started was too weak: the amount grows.
    assert episode.next_amount("returned") == pytest.approx(1.6)
    # Any other one cools the pump.
    for verdict in ("better", "moved", "worse"):
        assert episode.next_amount(verdict) == pytest.approx(0.4)
    assert not Episode(amount=1.0, stages=2, stage_iterations=4).pumping


def test_the_checkpoint_keeps_the_state_of_the_pump_apart():
    episode = Episode(amount=1.0, stages=2, stage_iterations=4, cycles=2)
    episode.batches = [ConstraintBatch(top=3)]
    episode.cycle_results.append({"cycle": 1})
    other = episode.copy()
    other.cycle_results.append({"cycle": 2})
    other.batches.append(ConstraintBatch(top=5))
    assert episode.cycle_results == [{"cycle": 1}]
    assert len(episode.batches) == 1


def test_a_pump_that_pushes_harder_each_time_is_limited_at_its_last_cycle(lso):
    pump = {**RELAX, "amount": 0.6, "cycles": 3, "decay": 1.4}
    with pytest.raises(RejectedDecisionError, match=r"at most 1.* at the last cycle"):
        check(decision(pump), lso, Limits.of(lso), 15, relaxation=STATE)
    check(decision({**pump, "decay": 0.7}), lso, Limits.of(lso), 15, relaxation=STATE)


@pytest.mark.parametrize("fields", [{"cycles": 0}, {"cycles": 7}, {"decay": 0.0}])
def test_the_cycles_and_the_decay_are_bounded(fields):
    with pytest.raises(ValueError):
        decision({**RELAX, **fields})


def pumping(cycles=2, decay=0.5, grow=1.0, **fields):
    state = {"asked": False}

    def act(context):
        relaxation = context["pilot"].get("relaxation", {})
        if state["asked"] or not relaxation.get("blocking"):
            return None
        state["asked"] = True
        return {
            "kind": "relax",
            "batches": [{"top": 4}],
            "amount": 0.3,
            "stages": 2,
            "stage_iterations": 2,
            "cycles": cycles,
            "decay": decay,
            "grow": grow,
            **fields,
        }

    return Scripted(act)


def test_a_pump_relaxes_and_restores_cycle_after_cycle(tmp_path):
    path = tmp_path / "journal.jsonl"
    backend = pumping()
    result = piloted(backend, tmp_path).execute(
        scenario(), "LSO_MMA", max_iter=40, **FAST
    )
    journal = list(read_journal(path))
    assert [d.action.kind for d in result.decisions] == ["relax"]
    assert len(result.segments) == 1  # Live: no new segment.
    events = [name for name, _ in relaxation_events(journal)]
    assert events == [
        "start",
        "step",
        "step",
        "cycle_end",
        "cycle",
        "step",
        "step",
        "cycle_end",
        "end",
    ]
    (second,) = [r for r in records(journal, "relaxation") if r["event"] == "cycle"]
    assert second["cycle"] == 2
    assert second["amount"] == pytest.approx(0.15)  # 0.3 times the decay.
    ends = [r for r in records(journal, "relaxation") if r["event"] == "cycle_end"]
    assert [r["cycle"] for r in ends] == [1, 2]
    # The constraints are back between the cycles, and after the last.
    relaxed = [record["relaxed"] for record in records(journal, "algorithm")]
    starts = [i for i in range(1, len(relaxed)) if relaxed[i] and not relaxed[i - 1]]
    assert len(starts) == 2
    assert relaxed[-1] == 0
    # A checkpoint was saved before each cycle.
    assert [r["reason"] for r in records(journal, "checkpoint")].count(
        "before_relax"
    ) >= 1


def test_claude_reads_the_cycles_of_a_pump(tmp_path):
    backend = pumping(cycles=2)
    piloted(backend, tmp_path).execute(scenario(), "LSO_MMA", max_iter=40, **FAST)
    during = [
        context["pilot"]["relaxation"]["under_way"]
        for context in backend.contexts
        if context["pilot"].get("relaxation", {}).get("active")
    ]
    assert during
    assert {item["cycles"] for item in during} == {2}
    assert {item["phase"] for item in during} >= {"relaxed"}
    assert {item["cycle"] for item in during} == {1, 2}
    # What the first cycle ended on is in the context of the second.
    later = [item for item in during if item["cycle"] == 2]
    assert later
    assert later[-1]["cycle_results"][0]["cycle"] == 1
    assert "best_feasible" in later[-1]["cycle_results"][0]


def test_a_pump_is_ended_by_tightening_everything(tmp_path):
    state = {"tightened": False}
    asking = pumping(cycles=3)
    first = asking.act

    def act(context):
        relaxation = context["pilot"].get("relaxation", {})
        under = relaxation.get("under_way", {})
        if under.get("cycle") == 2 and not state["tightened"]:
            state["tightened"] = True
            return {"kind": "tighten", "factor": 0.0}
        return first(context)

    asking.act = act
    path = tmp_path / "journal.jsonl"
    piloted(asking, tmp_path).execute(scenario(), "LSO_MMA", max_iter=40, **FAST)
    journal = list(read_journal(path))
    assert state["tightened"]
    events = [name for name, _ in relaxation_events(journal)]
    assert events.count("cycle") == 1  # The second cycle was the last.
    assert events[-1] == "end"
    assert records(journal, "algorithm")[-1]["relaxed"] == 0


def test_a_pump_whose_run_converges_goes_on_by_segments(tmp_path):
    path = tmp_path / "journal.jsonl"
    backend = pumping(cycles=2, stage_iterations=20)
    result = piloted(backend, tmp_path, EVERY_ONE).execute(
        scenario(), "LSO_MMA", max_iter=200, kkt_tolerance=0.5, **FAST
    )
    journal = list(read_journal(path))
    events = [name for name, _ in relaxation_events(journal)]
    assert events == [
        "start",
        "step",
        "step",
        "cycle_end",
        "cycle",
        "step",
        "step",
        "cycle_end",
        "end",
    ]
    # Each step and each settling is a segment: the run converges at each.
    assert len(result.segments) >= 5
    assert records(journal, "algorithm")[-1]["relaxed"] == 0
    assert result.stop_reason == "completed"


# What a cycle did, and how the pump answers.


def test_the_design_change_counts_the_variables_that_moved_by_a_tenth_of_a_range():
    start = np.array([0.0, 0.5, 1.0, 0.2])
    end = np.array([0.05, 0.7, 0.95, 0.2])
    change = design_change(start, end, np.zeros(4), np.ones(4))
    assert change["moved_share"] == pytest.approx(0.25)  # Only the second variable.
    assert change["mean_move"] == pytest.approx((0.05 + 0.2 + 0.05 + 0.0) / 4, abs=1e-5)
    assert design_change(start, start, np.zeros(4), np.ones(4))["moved_share"] == 0.0


@pytest.mark.parametrize(
    ("end", "moved", "verdict"),
    [
        (0.9, 0.0, "better"),
        (1.1, 0.5, "worse"),
        (1.0005, 0.5, "moved"),  # The same objective on another design.
        (1.0005, 0.001, "returned"),  # The same objective, the same design.
        (1.0005, 0.02, "moved"),
    ],
)
def test_a_cycle_ends_better_worse_moved_or_returned(end, moved, verdict):
    assert judge_cycle(1.0, end, moved) == verdict


def test_a_cycle_without_a_start_is_not_judged_a_failure():
    assert judge_cycle(None, 1.0, 0.0) == "moved"


def test_the_batches_grow_with_the_scale():
    batches = [
        ConstraintBatch(top=10),
        ConstraintBatch(share=0.5),
        ConstraintBatch(indices=[1, 2]),
    ]
    scaled = scaled_batches(batches, 2.0)
    assert scaled[0].top == 20
    assert scaled[1].share == pytest.approx(0.25)  # A lower threshold: more of them.
    assert scaled[2].indices == [1, 2]
    assert scaled_batches(batches, 1.0) == batches


def forced(monkeypatch, verdicts):
    """The pilot judges the cycles as ``verdicts`` say, then as ``moved``."""
    import gemseo_claude_pilot.pilot as pilot_module

    given = list(verdicts)
    monkeypatch.setattr(
        pilot_module,
        "judge_cycle",
        lambda start, end, moved: given.pop(0) if given else "moved",
    )


def test_a_cycle_that_ended_where_it_started_makes_the_next_one_stronger(
    tmp_path, monkeypatch
):
    forced(monkeypatch, ["returned", "returned"])
    path = tmp_path / "journal.jsonl"
    backend = pumping(cycles=3, decay=0.5, grow=2.0)
    piloted(backend, tmp_path).execute(scenario(), "LSO_MMA", max_iter=60, **FAST)
    journal = list(read_journal(path))
    cycles = [r for r in records(journal, "relaxation") if r["event"] == "cycle"]
    # 0.3 grows to 0.6, then to 1.2 held at the largest amount allowed, 1.0.
    assert [r["amount"] for r in cycles] == pytest.approx([0.6, 1.0])
    assert [r["after"] for r in cycles] == ["returned", "returned"]
    ends = [r for r in records(journal, "relaxation") if r["event"] == "cycle_end"]
    assert [r["verdict"] for r in ends][:2] == ["returned", "returned"]
    assert all("design_change" in r for r in ends)


def test_a_cycle_that_ended_better_cools_the_pump(tmp_path, monkeypatch):
    forced(monkeypatch, ["better", "moved"])
    path = tmp_path / "journal.jsonl"
    piloted(pumping(cycles=3, decay=0.5, grow=2.0), tmp_path).execute(
        scenario(), "LSO_MMA", max_iter=60, **FAST
    )
    cycles = [
        r
        for r in records(list(read_journal(path)), "relaxation")
        if r["event"] == "cycle"
    ]
    assert [r["amount"] for r in cycles] == pytest.approx([0.15, 0.075])


def test_a_cycle_that_ended_worse_is_undone_and_tried_again_smaller(
    tmp_path, monkeypatch
):
    forced(monkeypatch, ["worse"])
    path = tmp_path / "journal.jsonl"
    backend = pumping(cycles=2, decay=0.5, grow=2.0)
    result = piloted(backend, tmp_path).execute(
        scenario(), "LSO_MMA", max_iter=60, **FAST
    )
    journal = list(read_journal(path))
    events = [name for name, _ in relaxation_events(journal)]
    assert "ratchet" in events
    (ratchet,) = [r for r in records(journal, "relaxation") if r["event"] == "ratchet"]
    assert ratchet["amount"] == pytest.approx(0.15)  # 0.3 times the decay.
    assert ratchet["back_to"].startswith("it")
    # The run went back: a segment resumed the state saved before the cycle.
    assert len(result.segments) >= 2
    assert "resume" in [d.action.kind for d in result.decisions]
    iterations = [r["iteration"] for r in records(journal, "algorithm")]
    assert iterations.count(ratchet["iteration"] + 1) == 2
    # The return was the pump's: it does not count among those Claude may make.
    assert {
        context["pilot"]["checkpoints"]["resumes"]
        for context in backend.contexts
        if "checkpoints" in context["pilot"]
    } == {0}
    assert events[-1] == "end"
