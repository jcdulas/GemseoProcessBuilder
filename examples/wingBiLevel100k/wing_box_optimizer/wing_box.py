"""The wing box: its weight and its tip deflection, from 50,000 skin thicknesses.

The skins of the wing box carry the bending moment of the maneuver load, spread
along the span as an ellipse. The thickness of each station, from the root to
80 % of the half-span, makes the box heavier and stiffer. The deflection of
the tip comes from the unit load method: the sum over the stations of the
bending moment by the moment of a unit load at the tip, over the stiffness of
the box. Each station adds a term in 1/thickness: the deflection is
separable, which the MMA optimizer approximates exactly.

The thicknesses are relative to a reference: the uniform thickness meeting the
deflection limit on this wing under a load of 200 kN. The thickness a wing
needs varies as span**5 / area**3; relative to the reference, it stays of the
order of 1 whatever the wing, which keeps the optimizer well scaled.

The gradients are exact: they cost as much as the functions, whatever the
number of stations.
"""

from dataclasses import dataclass
from math import pi

from gemseo.core.discipline import Discipline
from gemseo.typing import StrKeyMapping
from numpy import arange, arcsin, array, float64, full, sqrt, zeros
from numpy.typing import NDArray

STATIONS = 50_000
"""The number of stations along the sized part of the half-span."""

SIZED_SPAN = 0.8
"""The share of the half-span whose skins are sized; the tip is lightly loaded."""

YOUNG_MODULUS = 7.0e10
"""The Young modulus of the skins (aluminium), in Pa."""

DEFLECTION_LIMIT = 0.04
"""The largest deflection of the tip, relative to the half-span."""

REFERENCE_LOAD = 200000.0
"""The load of the reference thickness, in N."""

SKIN_WEIGHT = 275000.0
"""The weight of the skins, with their stiffeners, in N per m3."""

FIXED_WEIGHT = 50000.0
"""The weight of the rest of the aircraft, without its wing, in N."""

WING_WEIGHT = 400.0
"""The weight of the wing without its box skins, in N per m2."""


def elliptic_moment(position: NDArray[float64]) -> NDArray[float64]:
    """Compute the bending moment of an elliptic lift, relative to its maximum.

    Args:
        position: The positions along the half-span, from 0 at the root to 1.

    Returns:
        The moment at each position, for a lift of 1 over a half-span of 1.

    """
    root = sqrt(1.0 - position**2)
    lever = pi / 4 - (position * root + arcsin(position)) / 2
    moment: NDArray[float64] = (
        4 / pi * ((1.0 - position**2) ** 1.5 / 3 - position * lever)
    )
    return moment


@dataclass(frozen=True)
class Sizing:
    """The deflection of the tip and the weight of the skins."""

    area: float
    span: float
    load: float
    relative_thickness: NDArray[float64]
    deflection_ratio: float
    """The deflection of the tip over its limit."""

    skins: float
    """The weight of the skins of the box, in N."""


class WingBox(Discipline):  # type: ignore[misc]  # GEMSEO is not typed.
    """The weight and the tip deflection of the wing, from its skin thicknesses."""

    default_grammar_type = Discipline.GrammarType.SIMPLE

    def __init__(self, stations: int = STATIONS) -> None:
        """Create the discipline and the stations of the wing box.

        Args:
            stations: The number of stations along the sized part of the span.

        """
        super().__init__(name="WingBox")
        defaults = {
            "area": array([30.0]),
            "span": array([15.0]),
            "load_max": array([200000.0]),
            "relative_thickness": full(stations, 1.0),
        }
        self.io.input_grammar.update_from_data(defaults)
        self.io.output_grammar.update_from_data(
            {"weight": zeros(1), "deflection_margin": zeros(1)}
        )
        self.default_input_data.update(defaults)
        position = SIZED_SPAN * (arange(stations) + 0.5) / stations
        self.width = SIZED_SPAN / stations
        self.chord = (1.0 - 0.6 * position) / 0.7
        """The chord of each station, relative to the mean chord of the wing."""

        # The deflection is load * span**6 / area**3 * sum(flexibility / thickness),
        # with the thickness in mm: the box is half as wide as the chord and 12 %
        # as high.
        self.flexibility = (
            elliptic_moment(position)
            * (1.0 - position)
            * self.width
            * 1000.0
            / (16.0 * YOUNG_MODULUS * 0.0036 * self.chord**3)
        )

    def reference_thickness(self, area: float, span: float) -> float:
        """Compute the uniform thickness meeting the deflection limit under 200 kN."""
        limit = DEFLECTION_LIMIT * span / 2
        flexibility = float(self.flexibility.sum())
        return REFERENCE_LOAD * span**6 / area**3 * flexibility / limit

    def size(self, data: StrKeyMapping) -> Sizing:
        """Compute the deflection of the tip and the weight of the skins."""
        area, span = float(data["area"][0]), float(data["span"][0])
        load, relative = float(data["load_max"][0]), data["relative_thickness"]
        # Relative to the reference, the deflection only depends on the load.
        spread = float(self.flexibility @ (1.0 / relative)) / self.flexibility.sum()
        thickness = self.reference_thickness(area, span) * relative
        skins = SKIN_WEIGHT * area * self.width / 1000.0 * float(thickness @ self.chord)
        return Sizing(area, span, load, relative, load / REFERENCE_LOAD * spread, skins)

    def _run(self, input_data: StrKeyMapping) -> StrKeyMapping:
        sizing = self.size(input_data)
        weight = FIXED_WEIGHT + WING_WEIGHT * sizing.area + sizing.skins
        return {
            "weight": full(1, weight),
            "deflection_margin": full(1, sizing.deflection_ratio - 1.0),
        }

    def _compute_jacobian(
        self, input_names: tuple[str, ...] = (), output_names: tuple[str, ...] = ()
    ) -> None:
        s = self.size(self.io.data)
        self._init_jacobian(input_names, output_names)
        weight, margin = self.jac["weight"], self.jac["deflection_margin"]
        # The skins grow as area * reference, that is as span**5 / area**2.
        reference = self.reference_thickness(s.area, s.span)
        d_skins = SKIN_WEIGHT * s.area * self.width / 1000.0 * self.chord * reference
        weight["relative_thickness"] = d_skins[None, :]
        weight["area"] = array([[WING_WEIGHT - 2 * s.skins / s.area]])
        weight["span"] = array([[5 * s.skins / s.span]])
        weight["load_max"] = zeros((1, 1))
        inverse = self.flexibility / s.relative_thickness**2
        spread = float(self.flexibility @ (1.0 / s.relative_thickness))
        margin["relative_thickness"] = (-s.deflection_ratio * inverse / spread)[None, :]
        margin["load_max"] = array([[s.deflection_ratio / s.load]])
        margin["span"] = zeros((1, 1))
        margin["area"] = zeros((1, 1))
