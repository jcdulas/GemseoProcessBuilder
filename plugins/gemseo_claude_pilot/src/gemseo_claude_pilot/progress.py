"""What a run gains per iteration, and what a decision did to it (pure functions).

They read the reports of the outer iterations of an algorithm (``iteration``,
``objective``, ``max_constraint``, ``kkt_residual``), whatever the problem:

- :func:`progress` measures a window of iterations;
- :func:`harm` says whether a change of settings made the run worse, to undo it;
- :func:`remaining_gain` estimates what the objective may still gain, to refuse
  a stop that gives up too early;
- :func:`merit` ranks the branches of a comparison started from the same state.
"""

import math
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

Report = Mapping[str, Any]

TINY = 1e-300


@dataclass(frozen=True)
class Progress:
    """How a run progresses over some outer iterations."""

    iterations: int
    gain: float
    """The relative gain of the objective per iteration: positive when it falls."""

    violation: float
    """The mean violation of the constraints (their maximum, when above 0)."""

    kkt: float
    """The mean KKT residual."""


@dataclass(frozen=True)
class TrialSettings:
    """When a change of settings is judged harmful."""

    window: int = 5
    """Outer iterations measured before the change, and after it."""

    slowdown: float = 0.5
    """The gain per iteration fell below this share of what it was..."""

    improvement: float = 0.8
    """...and neither the violation nor the KKT residual fell below this share
    of what it was."""


def progress(reports: Sequence[Report]) -> Progress | None:
    """The progress over some reports; ``None`` with fewer than two."""
    if len(reports) < 2:
        return None
    first = float(reports[0]["objective"])
    last = float(reports[-1]["objective"])
    gain = (first - last) / max(abs(first), TINY) / (len(reports) - 1)
    violation = float(np.mean([max(float(r["max_constraint"]), 0.0) for r in reports]))
    kkt = float(np.mean([float(r["kkt_residual"]) for r in reports]))
    return Progress(len(reports), gain, violation, kkt)


def harm(before: Progress, after: Progress, settings: TrialSettings) -> str:
    """Why a change made the run worse, or nothing if it did not.

    Worse: the run was descending and its gain per iteration at least halved,
    with no gain in feasibility nor in the KKT residual to pay for it.
    """
    if before.gain <= 0 or after.gain >= settings.slowdown * before.gain:
        return ""
    if after.violation < settings.improvement * before.violation:
        return ""
    if after.kkt < settings.improvement * before.kkt:
        return ""
    return (
        f"the objective gained {after.gain:.2%} per iteration instead of "
        f"{before.gain:.2%}, the violation of the constraints went from "
        f"{before.violation:.3g} to {after.violation:.3g} and the KKT residual "
        f"from {before.kkt:.3g} to {after.kkt:.3g}"
    )


@dataclass(frozen=True)
class RemainingGain:
    """What the objective may still gain, from its recent trend."""

    per_iteration: float
    """The recent gain per iteration, relative to the objective."""

    expected: float
    """The gain expected over the iterations left, relative to the objective."""

    iterations_left: int


def remaining_gain(
    reports: Sequence[Report], iterations_left: int, window: int = 5
) -> RemainingGain | None:
    """The gain the objective may still bring over the iterations left.

    The gains of the last two windows give how fast the descent slows down;
    the gain per iteration is taken to go on shrinking at that rate, which
    sums to a finite total. ``None`` with fewer than two windows of reports.
    """
    if len(reports) < 2 * window:
        return None
    now = progress(reports[-window:])
    before = progress(reports[-2 * window : -window])
    assert now is not None
    assert before is not None
    left = max(iterations_left, 0)
    if now.gain <= 0:
        return RemainingGain(now.gain, 0.0, left)
    ratio = now.gain / before.gain if before.gain > 0 else 1.0
    rate = min(max(ratio, 0.0) ** (1.0 / window), 0.97)
    total = 0.0 if rate <= 0 else now.gain * rate * (1.0 - rate**left) / (1.0 - rate)
    return RemainingGain(now.gain, total, left)


def merit(reports: Sequence[Report], start: float) -> float:
    """How good the end of a branch is: lower is better.

    The relative change of the objective since ``start``, plus the violation of
    the constraints, both averaged over the last three iterations of the branch.
    """
    last = reports[-3:]
    objective = float(np.mean([float(r["objective"]) for r in last]))
    violation = float(np.mean([max(float(r["max_constraint"]), 0.0) for r in last]))
    value = (objective - start) / max(abs(start), TINY) + violation
    return value if math.isfinite(value) else math.inf
