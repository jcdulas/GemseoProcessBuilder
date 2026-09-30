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


Action = Annotated[
    NoAction
    | ChangeSettings
    | ChangeDesignSpace
    | SwitchAlgorithm
    | Stop
    | AddSamples
    | ChangeSubScenario
    | Restart
    | Steer,
    Field(discriminator="kind"),
]


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


def decision_schema() -> dict[str, Any]:
    """The JSON schema of a decision: the input of the ``submit_decision`` tool."""
    return Decision.model_json_schema()
