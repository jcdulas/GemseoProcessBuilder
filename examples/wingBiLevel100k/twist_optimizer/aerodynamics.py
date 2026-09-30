"""The aerodynamics of the wing: its drag, from the twist of 50,000 sections.

Strip theory along the half-span: the angle of attack of the aircraft makes
the wing carry its weight, and the twist of each section changes how the lift
is spread along the span. Two drags follow:

- the profile drag of each section, which grows with the square of its lift
  coefficient: it wants the same lift coefficient everywhere;
- the induced drag, which grows with the distance of the lift from the ideal,
  elliptic, spread: it wants less lift at the tips.

The twist trades one for the other. Its gradient is exact: it costs as much as
the drag itself, whatever the number of sections.
"""

from dataclasses import dataclass
from math import pi

from gemseo.core.discipline import Discipline
from gemseo.typing import StrKeyMapping
from numpy import arange, array, float64, full, sqrt, zeros
from numpy.typing import NDArray

STATIONS = 50_000
"""The number of sections along the half-span, one twist each."""

DYNAMIC_PRESSURE = 3000.0
"""The dynamic pressure in cruise, in Pa."""

LIFT_SLOPE = 2 * pi / 180
"""The lift slope of a section, per degree."""

PROFILE_DRAG = 0.015
PROFILE_FACTOR = 0.01
"""The profile drag coefficient of a section: PROFILE_DRAG + PROFILE_FACTOR cl²."""

TWIST_COST = 1e-7
"""A small cost of twisting the wing, so that the twist has a single optimum."""


@dataclass(frozen=True)
class Flight:
    """The lift of the sections and the drag coefficients of the wing."""

    area: float
    span: float
    weight: float
    twist: NDArray[float64]
    aspect_ratio: float
    lift: float
    """The lift coefficient of the wing."""

    relative_twist: NDArray[float64]
    section_lift: NDArray[float64]
    """The lift coefficient of each section."""

    gap: NDArray[float64]
    """The lift of each section minus the elliptic one, both relative to the mean."""

    spread: float
    induced: float
    coefficient: float
    """The drag coefficient of the wing."""


class Aerodynamics(Discipline):  # type: ignore[misc]  # GEMSEO is not typed.
    """The drag of the wing in cruise, from its twist distribution."""

    default_grammar_type = Discipline.GrammarType.SIMPLE

    def __init__(self, stations: int = STATIONS) -> None:
        """Create the discipline and the sections of the half-span.

        Args:
            stations: The number of sections along the half-span.

        """
        super().__init__(name="Aerodynamics")
        defaults = {
            "area": array([30.0]),
            "span": array([15.0]),
            "weight": array([80000.0]),
            "twist": zeros(stations),
        }
        self.io.input_grammar.update_from_data(defaults)
        self.io.output_grammar.update_from_data({"drag": zeros(1)})
        self.default_input_data.update(defaults)
        position = (arange(stations) + 0.5) / stations
        chord = 1.0 - 0.6 * position  # A tapered wing.
        self.chord = chord / chord.mean()
        self.width = 1.0 / stations
        self.weights = self.chord * self.width
        """The share of the area of each section."""

        elliptic = sqrt(1.0 - position**2)
        self.elliptic = elliptic / (elliptic.sum() * self.width)
        """The ideal lift of each section, relative to the mean."""

    def fly(self, data: StrKeyMapping) -> Flight:
        """Compute the lift of the sections and the drag coefficients."""
        area, span = float(data["area"][0]), float(data["span"][0])
        weight, twist = float(data["weight"][0]), data["twist"]
        aspect_ratio = span**2 / area
        lift = weight / (DYNAMIC_PRESSURE * area)
        relative_twist = twist - self.weights @ twist
        section_lift = lift + LIFT_SLOPE * relative_twist
        gap = self.chord * section_lift / lift - self.elliptic
        spread = float(self.width * (gap @ gap))
        induced = lift**2 / (pi * aspect_ratio) * (1.0 + spread)
        profile = PROFILE_DRAG + PROFILE_FACTOR * float(self.weights @ section_lift**2)
        cost = TWIST_COST * float(self.weights @ twist**2)
        return Flight(
            area,
            span,
            weight,
            twist,
            aspect_ratio,
            lift,
            relative_twist,
            section_lift,
            gap,
            spread,
            induced,
            profile + induced + cost,
        )

    def _run(self, input_data: StrKeyMapping) -> StrKeyMapping:
        flight = self.fly(input_data)
        return {"drag": full(1, DYNAMIC_PRESSURE * flight.area * flight.coefficient)}

    def _compute_jacobian(
        self, input_names: tuple[str, ...] = (), output_names: tuple[str, ...] = ()
    ) -> None:
        f = self.fly(self.io.data)
        induced_factor = f.lift**2 / (pi * f.aspect_ratio)
        # The twist of a section moves its lift relative to the mean twist.
        weighted_gap = f.gap * self.chord
        d_spread = (
            2
            * self.width
            * LIFT_SLOPE
            / f.lift
            * (weighted_gap - self.weights * weighted_gap.sum())
        )
        d_twist = (
            2 * PROFILE_FACTOR * LIFT_SLOPE * self.weights * (f.section_lift - f.lift)
            + induced_factor * d_spread
            + 2 * TWIST_COST * self.weights * f.twist
        )
        # The lift coefficient of the wing moves the lift of every section.
        d_gap = -self.chord * LIFT_SLOPE * f.relative_twist / f.lift**2
        d_lift = (
            2 * PROFILE_FACTOR * f.lift
            + 2 * f.lift / (pi * f.aspect_ratio) * (1.0 + f.spread)
            + induced_factor * 2 * self.width * float(f.gap @ d_gap)
        )
        d_aspect_ratio = -f.induced / f.aspect_ratio
        pressure_area = DYNAMIC_PRESSURE * f.area
        d_area = DYNAMIC_PRESSURE * f.coefficient + pressure_area * (
            d_lift * -f.weight / (DYNAMIC_PRESSURE * f.area**2)
            + d_aspect_ratio * -(f.span**2) / f.area**2
        )
        self._init_jacobian(input_names, output_names)
        jacobian = self.jac["drag"]
        jacobian["twist"] = (pressure_area * d_twist)[None, :]
        jacobian["weight"] = array([[d_lift]])
        jacobian["span"] = array(
            [[pressure_area * d_aspect_ratio * 2 * f.span / f.area]]
        )
        jacobian["area"] = array([[d_area]])
