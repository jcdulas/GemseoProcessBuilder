"""Relaxing constraints that hold a run back, and the checkpoints to return to.

When the main run has converged, its multipliers say which constraints cost the
objective the most (spec § 4.12). Claude may elect a batch of them: the run goes
on from where it is on a problem where they are relaxed, ``g <= amount``, then
brings them back in steps, each once the objective has settled, down to the
original constraints. A relaxation is a continuation from a design the
constraints held back to one that satisfies them.

The pure part is here: the schedule of the steps, when a step is over, which
components a batch elects, what Claude reads of the constraints that block the
run, and the checkpoints it may return to.
"""

from collections.abc import Mapping
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from gemseo_claude_pilot.decisions import ConstraintBatch

STAGE_MIN = 2
"""The outer iterations a step lasts at least."""

SETTLED = 1e-3
"""The relative change of the objective over an iteration under which it has
settled, over two iterations in a row."""

MAX_CHECKPOINTS = 8
"""The checkpoints kept: the oldest periodic ones go first."""

BLOCKING_TOP = 15
"""The components shown to Claude for each constraint, largest multiplier first."""

CUMULATIVE = (10, 100, 1000)
"""The numbers of components whose share of the multipliers is shown."""

ACTIVE_SHARE = 1e-6
"""A multiplier above this share of the largest one marks an active component."""

RETURN_TOLERANCE = 0.002
"""A cycle that ends within this share of the objective it started from has not
gained nor lost anything."""

MOVED_SHARE = 0.02
"""A cycle moved the design when this share of the variables, or more, changed."""

MOVED_RANGE = 0.1
"""A variable changed when it moved by more than this share of its range."""

PERIODIC = "periodic"
"""The reason of a checkpoint saved at a consultation; the first ones dropped."""

Array = NDArray[np.float64]


@dataclass
class Episode:
    """A relaxation under way: the steps by which its constraints come back."""

    amount: float
    """The relaxation at first, in the units of the constraints."""

    stages: int
    """The steps by which the amount falls to zero."""

    stage_iterations: int
    """The outer iterations a step lasts, at most."""

    components: int = 0
    names: list[str] = field(default_factory=list)
    stage: int = 0
    """The steps done."""

    since: int = 0
    """The outer iteration the current step started at."""

    before: float | None = None
    """The best feasible objective when the constraints were relaxed."""

    curve: list[dict[str, Any]] = field(default_factory=list)
    """The objective and the true violation at the end of each step."""

    cycles: int = 1
    """The cycles of a pump: relaxed, brought back by steps, then settled at the
    original constraints, as many times (1: a single relaxation, which ends when its
    constraints are back)."""

    cycle: int = 0
    """The cycles done."""

    decay: float = 0.7
    """The amplitude of a cycle, relative to the one before."""

    base_amount: float = 0.0
    """The amount of the first cycle."""

    cycle_stages: int = 0
    """The steps of each cycle."""

    phase: str = "relaxed"
    """``relaxed``: the constraints are relaxed or coming back; ``settle``: they are
    back, and the run settles at the original constraints, which ends a cycle."""

    batches: list[Any] = field(default_factory=list)
    """What each cycle elects its components from (its multipliers, then)."""

    cycle_results: list[dict[str, Any]] = field(default_factory=list)
    """What each cycle ended on: the objective, the true violation, the best
    feasible objective then, how far the design moved and the verdict."""

    grow: float = 1.0
    """The factor of the amount and of the batch of the next cycle when a cycle
    ended where it started (the relaxation was too weak to leave the basin)."""

    batch_scale: float = 1.0
    """What the ``top`` of the batches is multiplied by, and their ``share``
    divided by, since the cycles that ended where they started."""

    start_objective: float | None = None
    """The objective the current cycle started from."""

    start_x: Any = None
    """The design the current cycle started from."""

    start_checkpoint: str = ""
    """The checkpoint saved before the current cycle, to return to if it ends worse."""

    def amount_left(self) -> float:
        """The relaxation now."""
        return self.amount * (self.stages - self.stage) / self.stages

    def factor(self) -> float:
        """The factor of the next tightening: the amount falls by equal parts."""
        left = self.stages - (self.stage + 1)
        return left / (left + 1)

    @property
    def over(self) -> bool:
        """Whether every step is done: the constraints are the original ones."""
        return self.stage >= self.stages

    @property
    def pumping(self) -> bool:
        """Whether the relaxation repeats."""
        return self.cycles > 1

    def next_amount(self, verdict: str = "moved") -> float:
        """The amount of the next cycle, from how the last one ended.

        A cycle that ended where it started was too weak: the amount grows (by
        ``grow``). Any other one brings the pump to cool: it falls by ``decay``.
        """
        return self.amount * (self.grow if verdict == "returned" else self.decay)

    def copy(self) -> "Episode":
        """An independent copy, to keep with a checkpoint."""
        return deepcopy(self)


def stage_over(episode: Episode, objectives: Sequence[float], iteration: int) -> str:
    """Why the current step is over, or nothing if it goes on.

    Args:
        episode: The relaxation.
        objectives: The objective at the last outer iterations.
        iteration: The outer iteration reached.
    """
    since = iteration - episode.since
    if since >= episode.stage_iterations:
        return f"its {episode.stage_iterations} iterations are spent"
    if since >= STAGE_MIN and len(objectives) >= 3:
        last = objectives[-3:]
        scale = max(abs(last[-1]), 1e-300)
        changes = [abs(last[i + 1] - last[i]) / scale for i in range(2)]
        if max(changes) <= SETTLED:
            return "the objective has settled"
    return ""


def design_change(start: Any, end: Any, lower: Any, upper: Any) -> dict[str, float]:
    """How far the design moved between two iterates of a cycle.

    The share of the variables that changed by more than a tenth of their range,
    and the mean move, as a share of the range.
    """
    ranges = np.maximum(np.asarray(upper, float) - np.asarray(lower, float), 1e-300)
    moves = np.abs(np.asarray(end, float) - np.asarray(start, float)) / ranges
    if not moves.size:
        return {"moved_share": 0.0, "mean_move": 0.0}
    return {
        "moved_share": round(float(np.mean(moves > MOVED_RANGE)), 4),
        "mean_move": round(float(np.mean(moves)), 5),
    }


def judge_cycle(
    start_objective: float | None, end_objective: float | None, moved_share: float
) -> str:
    """How a cycle of the pump ended.

    ``better``: the objective fell; ``worse``: it rose; ``moved``: the same
    objective on another design; ``returned``: the same objective on the same
    design, the relaxation was too weak to leave the basin.
    """
    if start_objective is None or end_objective is None:
        return "moved"
    change = (end_objective - start_objective) / max(abs(start_objective), 1e-300)
    if change <= -RETURN_TOLERANCE:
        return "better"
    if change >= RETURN_TOLERANCE:
        return "worse"
    return "moved" if moved_share >= MOVED_SHARE else "returned"


def scaled_batches(
    batches: Sequence[ConstraintBatch], scale: float
) -> list[ConstraintBatch]:
    """The batches with more components: ``top`` times ``scale``, ``share`` over it."""
    if scale == 1.0:
        return list(batches)
    return [
        batch.model_copy(
            update={
                "top": None if batch.top is None else max(int(batch.top * scale), 1),
                "share": None
                if batch.share is None
                else max(batch.share / scale, 1e-3),
            }
        )
        for batch in batches
    ]


def select(
    multipliers: Mapping[str, Array],
    batches: Sequence[ConstraintBatch],
) -> dict[str, NDArray[np.int64]]:
    """The components a relaxation elects, by constraint.

    A batch gives the components with the largest multipliers (``top``), those
    within a share of the largest one (``share``), or their indices.

    Raises:
        ValueError: When a batch names no constraint of the problem.
    """
    chosen: dict[str, set[int]] = {}
    for batch in batches:
        name = batch.constraint
        if name is None and len(multipliers) == 1:
            name = next(iter(multipliers))
        if name is None or name not in multipliers:
            known = ", ".join(multipliers) or "none"
            msg = (
                f"Unknown constraint {batch.constraint}; the constraints are: {known}."
            )
            raise ValueError(msg)
        values: Array = np.asarray(multipliers[name])
        elected: Sequence[int]
        if batch.indices is not None:
            elected = [i for i in batch.indices if 0 <= i < values.size]
        else:
            largest = float(values.max(initial=0.0))
            if largest <= 0:
                elected = []
            elif batch.share is not None:
                elected = np.flatnonzero(values >= batch.share * largest).tolist()
            else:
                assert batch.top is not None
                order = np.argsort(-values, kind="stable")[: batch.top]
                elected = [int(i) for i in order if values[i] > 0]
        chosen.setdefault(name, set()).update(int(i) for i in elected)
    return {
        name: np.array(sorted(indices), dtype=np.int64)
        for name, indices in chosen.items()
        if indices
    }


def blocking(multipliers: Mapping[str, Array]) -> dict[str, Any]:
    """What Claude reads of the constraints that cost the objective the most.

    For each constraint: its size, the components with a multiplier, the largest
    ones (their index and their multiplier as a share of the largest), and the
    share of the total multiplier that the first 10, 100 and 1,000 hold: how
    concentrated the blocking is.
    """
    largest = max(
        (float(np.max(values, initial=0.0)) for values in multipliers.values()),
        default=0.0,
    )
    if largest <= 0:
        return {}
    result: dict[str, Any] = {}
    for name, raw in multipliers.items():
        values = np.asarray(raw, dtype=float)
        active = int(np.count_nonzero(values > ACTIVE_SHARE * largest))
        if not active:
            continue
        order = np.argsort(-values, kind="stable")
        total = float(values.sum())
        result[name] = {
            "components": int(values.size),
            "with_multiplier": active,
            "top": [
                [int(i), round(float(values[i]) / largest, 4)]
                for i in order[:BLOCKING_TOP]
                if values[i] > 0
            ],
            "cumulative_share": {
                str(k): round(float(values[order[:k]].sum()) / total, 3)
                for k in CUMULATIVE
                if k < active
            },
        }
    return result


@dataclass
class Checkpoint:
    """An earlier state of the optimizer that the run may return to."""

    id: str
    iteration: int
    objective: float
    max_constraint: float
    reason: str
    path: Path
    relaxed: int = 0
    episode: Episode | None = None
    """The relaxation under way when it was saved, to go on with it."""

    x: Any = None
    """The design at the iterate it holds."""

    def describe(self) -> dict[str, Any]:
        """What Claude reads of it."""
        data: dict[str, Any] = {
            "id": self.id,
            "iteration": self.iteration,
            "objective": round(self.objective, 6),
            "max_constraint": round(self.max_constraint, 6),
            "reason": self.reason,
        }
        if self.relaxed:
            data["relaxed_components"] = self.relaxed
        return data


def prune(checkpoints: list[Checkpoint], limit: int = MAX_CHECKPOINTS) -> list[Path]:
    """Drop the oldest periodic checkpoints beyond ``limit``; the files to delete."""
    dropped = []
    while len(checkpoints) > limit:
        victim = next((c for c in checkpoints if c.reason == PERIODIC), None)
        if victim is None:
            victim = checkpoints[0]
        checkpoints.remove(victim)
        dropped.append(victim.path)
    return dropped
