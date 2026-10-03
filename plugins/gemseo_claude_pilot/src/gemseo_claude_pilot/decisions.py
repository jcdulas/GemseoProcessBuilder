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
    "stop_explorations",
    "relax",
    "tighten",
    "resume",
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
    "stop_explorations",
    "relax",
    "tighten",
    "resume",
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
        default=10,
        ge=3,
        le=50,
        description="Outer iterations of each exploration; the user's limit (10 by "
        "default) bounds it.",
    )


class Adopt(_Strict):
    """Move the main run onto an exploration that ended: its design and its state."""

    kind: Literal["adopt"] = "adopt"
    exploration: str = Field(min_length=1, description="The label of the exploration.")


class StopExplorations(_Strict):
    """End explorations that are running, at the end of their current iteration.

    They stop on a feasible point and report what they reached, as if they had
    run their iterations: shorter, and still adoptable.
    """

    kind: Literal["stop_explorations"] = "stop_explorations"
    explorations: list[str] = Field(
        default_factory=list,
        description="The labels to stop; all the running ones if empty.",
    )


class ConstraintBatch(_Strict):
    """Components of an inequality constraint, chosen by their multiplier."""

    constraint: str | None = Field(
        default=None,
        description="The constraint (its name in the problem); the only one if "
        "there is one.",
    )
    top: int | None = Field(
        default=None,
        ge=1,
        le=100_000,
        description="The components with the largest multipliers: the ones that "
        "cost the objective the most.",
    )
    share: float | None = Field(
        default=None,
        gt=0,
        le=1,
        description="The components whose multiplier is at least this share of "
        "the largest one.",
    )
    indices: list[int] | None = Field(
        default=None,
        min_length=1,
        max_length=100_000,
        description="The components, by their index in the constraint.",
    )

    def model_post_init(self, __context: Any) -> None:
        """Check that the components are chosen in one way."""
        chosen = [x for x in (self.top, self.share, self.indices) if x is not None]
        if len(chosen) != 1:
            msg = "Give exactly one of top, share and indices."
            raise ValueError(msg)


class Relax(_Strict):
    """Relax a batch of constraints that hold the run back, then bring them back.

    The run goes on, from where it is and with its state, on a problem where
    these components of the constraints are ``g <= amount`` instead of
    ``g <= 0``: it may leave the domain and reorganize. They are then brought
    back in ``stages`` steps, each once the objective has settled, down to the
    original constraints: the run returns to the feasible domain, possibly on a
    better design. The reports, the best feasible point and the result stay those
    of the original problem. Only for the large-scale optimizer.
    """

    kind: Literal["relax"] = "relax"
    batches: list[ConstraintBatch] = Field(min_length=1, max_length=3)
    amount: float = Field(
        gt=0,
        description="By how much, in the units of the constraint (standardized "
        "as g <= 0): the violation allowed at first, as the max_constraint of the "
        "reports reads.",
    )
    stages: int = Field(
        default=4,
        ge=1,
        le=8,
        description="The steps by which the constraints come back, the amount "
        "falling by the same part at each, to zero at the last.",
    )
    stage_iterations: int = Field(
        default=6,
        ge=2,
        le=20,
        description="The outer iterations a step lasts, at most: it ends earlier "
        "once the objective has settled.",
    )
    cycles: int = Field(
        default=1,
        ge=1,
        le=6,
        description="A pump when above 1: the relaxation is repeated. Each cycle "
        "relaxes, brings the constraints back by steps, then lets the run settle at "
        "the original constraints; the next one starts from there, its batch elected "
        "again from the multipliers of that design (top and share), its amount the "
        "previous one times decay.",
    )
    decay: float = Field(
        default=0.7,
        gt=0,
        le=1.5,
        description="The amount of a cycle relative to the one before when it "
        "left the design where it was or made it better: under 1 the pump cools.",
    )
    grow: float = Field(
        default=1.6,
        ge=1,
        le=3,
        description="When a cycle ended where it started (the same objective on "
        "the same design: too weak to leave the basin) the next one relaxes this "
        "many times more, on this many times more components. A cycle that ended "
        "worse is undone: the run returns to its state before it, with the amount "
        "of the one before times decay.",
    )


class Tighten(_Strict):
    """Bring the relaxed constraints back now, by a factor of their amount."""

    kind: Literal["tighten"] = "tighten"
    factor: float = Field(
        default=0.0,
        ge=0,
        lt=1,
        description="The amount left is multiplied by it; 0 brings the constraints "
        "back at once.",
    )


class Resume(_Strict):
    """Go on from a checkpoint of the run: an earlier state of the optimizer.

    The run forgets what it did since: its iterates and reports after that
    iteration are dropped from the history you read (the evaluations stay spent
    in the budget, and the best feasible design met stays the best). The state
    returns with its multipliers, asymptotes and relaxation.
    """

    kind: Literal["resume"] = "resume"
    checkpoint: str = Field(
        min_length=1, description="The id of the checkpoint (pilot.checkpoints)."
    )
    settings: dict[str, Any] = Field(
        default_factory=dict,
        description="Settings of the optimizer that change from there, as in "
        "change_settings; the others keep their value.",
    )


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
    | Adopt
    | StopExplorations
    | Relax
    | Tighten
    | Resume,
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
