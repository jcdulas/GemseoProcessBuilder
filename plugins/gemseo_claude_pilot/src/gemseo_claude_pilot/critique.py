"""The critique of an analysis: the review of heavy decisions, and the forecasts.

An engineer does not act on his first analysis. Two mechanisms put that
discipline in the pilot, for any problem:

- a *heavy* decision (it ends the run, changes its strategy or its design) is
  sent back once to Claude, to be reviewed as a senior engineer would review a
  colleague's: the strongest argument against it, the best use of what the
  budget still allows, and whether its earlier predictions held
  (:func:`review_request`);
- the *prediction* of an assessment is a measurable statement about the next
  outer iterations; the pilot reads it when it falls due and tells Claude
  whether it held (:func:`verdict`), with the record of its predictions so far.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.decisions import Prediction

REVIEW_MARKER = "Review before this takes effect"
"""What a request for review starts with: a fake backend recognizes it."""

HEAVY_ACTIONS = frozenset(
    {
        "stop",
        "compare",
        "restart",
        "steer",
        "switch_algorithm",
        "change_design_space",
        "restore_feasibility",
        "relax",
        "resume",
        "explore",
        "adopt",
    }
)
"""The actions reviewed before they take effect: they end the run, or change its
strategy or its design, and cost more than a setting to undo."""

FLOOR = {"objective": 1e-300, "max_constraint": 1e-2, "kkt_residual": 1e-300}
"""What a change of each metric is relative to, at least: a violation near 0 is
read against 1 % of the limit."""

STAYS = 0.05
"""The relative change under which a metric that was to stay did."""


def review_request(
    decision: Decision,
    evaluations_left: int,
    iterations_left: int | None,
    record: Mapping[str, Any] | None,
) -> str:
    """The request to review a heavy decision, sent to Claude as the answer of the tool.

    Args:
        decision: The decision under review.
        evaluations_left: The evaluations the budget still allows.
        iterations_left: The outer iterations they make, at the rate of the run;
            ``None`` for an algorithm that reports none.
        record: The predictions made so far and how many held.
    """
    left = f"{evaluations_left} evaluations"
    if iterations_left is not None:
        left += f" (about {iterations_left} outer iterations)"
    lines = [
        f"{REVIEW_MARKER} (`{decision.action.kind}`): read it as a senior "
        "optimization engineer would read a colleague's, then submit again.",
        "",
        "1. The strongest argument against it, from the data in the context: "
        "what would you see if it were wrong? Look for it (the read tools), do "
        "not assume it is absent.",
        f"2. The budget still allows {left}. What is the best use of it: the run "
        "unchanged, another strategy, a comparison of strategies? Why is this "
        "decision better than going on, in what the next iterations can still bring?",
    ]
    if decision.action.kind == "stop":
        lines.append(
            "3. A stop forgoes everything the budget left allows: say what "
            "makes more iterations not worth their cost, with a number."
        )
    if record and record.get("made"):
        lines.append(
            f"{len(lines) - 1}. Your predictions so far: {record['confirmed']} "
            f"held out of {record['made']}. Weigh the confidence of this one "
            "accordingly."
        )
    lines += [
        "",
        "Then call submit_decision again: the same decision if it stands, a "
        "revised one, or `none`. Say in the rationale what the review changed, "
        "or why nothing did.",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class Verdict:
    """Whether a prediction held, and what was seen."""

    held: bool
    text: str


def verdict(prediction: Prediction, before: float, now: float) -> Verdict:
    """Whether a prediction held, from the metric when it was made and when it fell due.

    Args:
        prediction: What was predicted.
        before: The metric at the report the decision was made at.
        now: The metric when the prediction fell due.
    """
    change = (now - before) / max(abs(before), FLOOR[prediction.metric])
    seen = (
        f"{prediction.metric} went from {before:.4g} to {now:.4g} "
        f"({change:+.1%}) within {prediction.within} outer iterations"
    )
    if prediction.expect == "stays":
        bound = prediction.by or STAYS
        held = abs(change) <= bound
        wanted = f"to stay within {bound:.1%}"
    elif prediction.expect == "falls":
        held = change < 0 and (prediction.by is None or -change >= prediction.by)
        wanted = "to fall" + _by(prediction.by)
    else:
        held = change > 0 and (prediction.by is None or change >= prediction.by)
        wanted = "to rise" + _by(prediction.by)
    return Verdict(
        held, f"{'Held' if held else 'Did not hold'}: expected {wanted}; {seen}."
    )


def _by(by: float | None) -> str:
    return "" if by is None else f" by at least {by:.1%}"
