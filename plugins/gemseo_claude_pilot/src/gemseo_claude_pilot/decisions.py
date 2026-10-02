"""The decisions Claude answers with (spec § 4.3, § 4.5).

A decision is a diagnosis and at most one action. Claude gives it as the input
of the ``submit_decision`` tool, whose schema is :func:`decision_schema`.

Example:
    >>> Decision.model_validate(
    ...     {
    ...         "diagnosis": "The step is at the tolerance.",
    ...         "action": {"kind": "change_settings", "settings": {"xtol_rel": 1e-8}},
    ...     }
    ... ).action.kind
    'change_settings'
"""

from typing import Annotated
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from gemseo_claude_pilot.design import Transform

ActionKind = Literal[
    "none",
    "change_settings",
    "change_design_space",
    "switch_algorithm",
    "stop",
    "add_samples",
    "change_sub_scenario",
    "restart",
    "steer",
    "compare",
    "restore_feasibility",
    "explore",
    "adopt",
]

ACTION_KINDS: tuple[ActionKind, ...] = (
    "none",
    "change_settings",
    "change_design_space",
    "switch_algorithm",
    "stop",
    "add_samples",
    "change_sub_scenario",
    "restart",
    "steer",
    "compare",
    "restore_feasibility",
    "explore",
    "adopt",
)

Values = float | list[float]
"""A value for every component of a variable, or one value for all of them."""


class _Strict(BaseModel):
    """Refuses the fields it does not know: a typo must not go unnoticed."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class NoAction(_Strict):
    """Keep going as is."""

    kind: Literal["none"] = "none"


class ChangeSettings(_Strict):
    """New values of settings of the current algorithm."""

    kind: Literal["change_settings"] = "change_settings"
    settings: dict[str, Any] = Field(min_length=1)


class VariableChange(_Strict):
    """New bounds and/or a new starting value of a design variable."""

    name: str
    lower: Values | None = None
    upper: Values | None = None
    value: Values | None = None


class ChangeDesignSpace(_Strict):
    """New bounds or starting values of some design variables."""

    kind: Literal["change_design_space"] = "change_design_space"
    variables: list[VariableChange] = Field(min_length=1)


class SwitchAlgorithm(_Strict):
    """Another algorithm, with its settings."""

    kind: Literal["switch_algorithm"] = "switch_algorithm"
    algo_name: str
    settings: dict[str, Any] = Field(default_factory=dict)


class Stop(_Strict):
    """Stop the run."""

    kind: Literal["stop"] = "stop"
    reason: Literal["converged", "hopeless", "budget"]


class AddSamples(_Strict):
    """A new sampling segment of a DOE, optionally in a sub-region."""

    kind: Literal["add_samples"] = "add_samples"
    algo_name: str
    n_samples: int = Field(gt=0)
    settings: dict[str, Any] = Field(default_factory=dict)
    region: list[VariableChange] = Field(default_factory=list)


class ChangeSubScenario(_Strict):
    """Another algorithm, or other settings, of a sub-optimization of a BiLevel study.

    Applied from the next system iteration, without ending the segment.
    """

    kind: Literal["change_sub_scenario"] = "change_sub_scenario"
    scenario: str
    algo_name: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class Restart(_Strict):
    """A new segment from another design: a past one, transformed on its grid.

    Only for a model that describes the physics of its design (spec § 4.8).
    """

    kind: Literal["restart"] = "restart"
    answers: str = Field(
        min_length=1,
        description="The physical diagnosis this restart answers, in one sentence.",
    )
    base: Literal["best", "current"] | int = Field(
        default="best",
        description="The design to start from: best, current, or an evaluation.",
    )
    transforms: list[Transform] = Field(
        default_factory=list,
        description="The transformations of the base design, in order "
        "(list_design_transforms).",
    )


class Anticipate(_Strict):
    """Extrapolate the trend of the design: ``x + factor (x - x_past)``."""

    iterations: int = Field(
        default=5, ge=1, le=20, description="The iterates the trend is measured over."
    )
    factor: float = Field(
        default=1.0,
        gt=0,
        le=3,
        description="How far to go along the trend: 1 goes as far again.",
    )


class VariableValue(_Strict):
    """A new value of a design variable."""

    name: str
    value: Values


class Steer(_Strict):
    """Move the current design toward where it heads, the optimizer going on.

    Applied at the next outer iteration of ``LSO_MMA`` and ``LSO_GCMMA``
    without a new segment (their state kept); a new segment from the moved
    design for other algorithms. In order: ``anticipate``, ``transforms`` (a
    model describing its design, spec § 4.8), ``variables``; clipped into the
    bounds.
    """

    kind: Literal["steer"] = "steer"
    toward: str = Field(
        min_length=1,
        description="Where the design is heading, and why this move gets "
        "there in fewer iterations.",
    )
    anticipate: Anticipate | None = None
    transforms: list[Transform] = Field(default_factory=list)
    variables: list[VariableValue] = Field(default_factory=list)


class Perturbation(_Strict):
    """A random move of every design variable, a share of its range."""

    scale: float = Field(
        gt=0, le=0.5, description="The standard deviation, a share of the range."
    )
    seed: int = Field(default=0, description="Another seed, another random move.")


class ExploreStart(_Strict):
    """A starting design of an exploration, from a design of the run."""

    label: str = Field(
        min_length=1, max_length=40, description="A short name, to tell them apart."
    )
    why: str = Field(
        min_length=1,
        description="Why this zone is worth a look: what you read of the space.",
    )
    base: Literal["best", "current"] | int = Field(
        default="best",
        description="The design to start from: the best feasible, the current "
        "iterate, or an evaluation.",
    )
    anticipate: Anticipate | None = Field(
        default=None, description="With the current iterate only."
    )
    transforms: list[Transform] = Field(default_factory=list)
    variables: list[VariableValue] = Field(default_factory=list)
    perturb: Perturbation | None = None


class Explore(_Strict):
    """Explore other zones of the design space, in processes you do not guide.

    Each start runs the user's algorithm and settings for up to ``iterations``
    outer iterations, in a process of its own, while the main run goes on; you
    are consulted when they have ended, with what each reached and how it was
    still progressing, and may ``adopt`` one. At most four starts.
    """

    kind: Literal["explore"] = "explore"
    starts: list[ExploreStart] = Field(min_length=1, max_length=4)
    iterations: int = Field(
        default=50, ge=10, le=50, description="Outer iterations of each exploration."
    )


class Adopt(_Strict):
    """Move the main run onto an exploration that ended: its design and its state."""

    kind: Literal["adopt"] = "adopt"
    exploration: str = Field(min_length=1, description="The label of the exploration.")


class Option(_Strict):
    """One strategy of a comparison."""

    label: str = Field(
        min_length=1, description="A short name, to tell the branches apart."
    )
    settings: dict[str, Any] = Field(
        default_factory=dict,
        description="Settings of the algorithm for this branch; the others keep "
        "their value.",
    )
    algo_name: Literal["LSO_MMA", "LSO_GCMMA"] | None = Field(
        default=None, description="The method of this branch; the current one if none."
    )


class Compare(_Strict):
    """Try other strategies from the current state, and keep the best.

    Every branch, and the current strategy as a reference, runs the same number
    of outer iterations from the state the optimizer is in; the one whose end
    is best (objective, then feasibility) goes on, the others are dropped. The
    iterations of all the branches are spent from the budget. Only for the
    large-scale optimizer, which saves and resumes its state exactly.
    """

    kind: Literal["compare"] = "compare"
    options: list[Option] = Field(min_length=1, max_length=2)
    iterations: int = Field(
        default=5, ge=3, le=10, description="Outer iterations of each branch."
    )


class RestoreFeasibility(_Strict):
    """Bring the iterate back within the constraints now.

    Smaller moves and a heavier cost of the violation, until the point is
    feasible: what the optimizer does by itself near the end of its budget,
    asked for earlier. Only for the large-scale optimizer, when its iterate
    violates a constraint.
    """

    kind: Literal["restore_feasibility"] = "restore_feasibility"


Action = Annotated[
    NoAction
    | ChangeSettings
    | ChangeDesignSpace
    | SwitchAlgorithm
    | Stop
    | AddSamples
    | ChangeSubScenario
    | Restart
    | Steer
    | Compare
    | RestoreFeasibility
    | Explore
    | Adopt,
    Field(discriminator="kind"),
]


class Hypothesis(_Strict):
    """An explanation of what the run does, with what supports and what opposes it."""

    claim: str = Field(min_length=1)
    evidence_for: str = Field(
        min_length=1, description="The data in the context that support it."
    )
    evidence_against: str = Field(
        min_length=1,
        description="The data that do not fit it, or that would, if you were wrong; "
        "say 'none found' only after looking.",
    )


class Alternative(_Strict):
    """Another course of action that was considered, and why it was not taken."""

    action: str = Field(min_length=1)
    why_not: str = Field(min_length=1)


class Prediction(_Strict):
    """What the run will show if the analysis is right, checked by the pilot."""

    metric: Literal["objective", "max_constraint", "kkt_residual"]
    expect: Literal["falls", "rises", "stays"]
    within: int = Field(
        ge=1, le=30, description="Outer iterations after the decision it is read at."
    )
    by: float | None = Field(
        default=None,
        gt=0,
        description="The relative change at least (falls, rises) or at most (stays) "
        "that makes the prediction right; a violation is read against 1 % of the "
        "limit when it is near 0. 5 % for stays if omitted.",
    )


class Assessment(_Strict):
    """The critique of an engineer on his own analysis, which comes with an action.

    What a senior engineer would ask of a colleague's analysis before acting on
    it: the explanations considered and what is against each, where the
    analysis may be wrong, the other courses of action, and what the next
    iterations will show if it is right.
    """

    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=3)
    weaknesses: list[str] = Field(
        min_length=1,
        description="Where this analysis may be wrong, and what would show it.",
    )
    alternatives: list[Alternative] = Field(min_length=1, max_length=3)
    prediction: Prediction | None = Field(
        default=None,
        description="A measurable prediction of the next iterations, which the "
        "pilot checks and reports at your next call, with your record.",
    )


class Decision(_Strict):
    """A diagnosis of the run and at most one action."""

    diagnosis: str = Field(description="What is happening, in one or two sentences.")
    severity: Literal["info", "warning", "problem"] = "info"
    action: Action = Field(default_factory=NoAction)
    rationale: str = Field(
        default="", description="Why this action, in two or three sentences."
    )
    expected_effect: str = Field(
        default="", description="What should be seen in the next iterations."
    )
    confidence: float = Field(default=0.5, ge=0, le=1)
    assessment: Assessment | None = Field(
        default=None,
        description="Required with any action: your critique of your own analysis.",
    )
    review_in: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description="With the large-scale optimizer: the outer iterations that "
        "go on without you before you are consulted again (the pilot bounds it, "
        "and a serious symptom calls you sooner). Give it from the time of an "
        "iteration and of a call (`pilot.timing`) and from how the run is doing: "
        "few when it needs watching, many when it is healthy.",
    )


def decision_schema() -> dict[str, Any]:
    """The JSON schema of a decision: the input of the ``submit_decision`` tool."""
    return Decision.model_json_schema()
