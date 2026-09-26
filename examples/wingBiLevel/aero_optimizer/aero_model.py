"""The normal aerodynamic model of the wing.

It stands for a costly aerodynamic solver: the drag of the wing in cruise and
the load of the maneuver. The camber of the airfoil is its own design variable:
a cambered airfoil has more profile drag, but spreads the lift better along
the span.
"""

from math import pi

from gemseo.core.discipline import Discipline
from gemseo.typing import StrKeyMapping
from numpy import array, float64
from numpy.typing import NDArray

DYNAMIC_PRESSURE = 3000.0
"""The dynamic pressure in cruise, in Pa."""


def aerodynamics(
    area: NDArray[float64],
    span: NDArray[float64],
    weight: NDArray[float64],
    camber: NDArray[float64],
) -> dict[str, NDArray[float64]]:
    """Compute the drag in cruise and the load of the maneuver.

    Args:
        area: The area of the wing, in m2.
        span: The span of the wing, in m.
        weight: The weight of the aircraft, in N.
        camber: The camber of the airfoil, relative to its chord.

    Returns:
        The drag, in N, and the maximum load, in N.

    """
    aspect_ratio = span**2 / area
    lift_coefficient = weight / (DYNAMIC_PRESSURE * area)
    profile_drag = 0.02 + 0.5 * (camber - 0.03) ** 2
    efficiency = 0.75 + 2.0 * camber
    induced_drag = lift_coefficient**2 / (pi * efficiency * aspect_ratio)
    drag = DYNAMIC_PRESSURE * area * (profile_drag + induced_drag)
    return {"drag": drag, "load_max": 2.5 * weight}


class AeroModel(Discipline):  # type: ignore[misc]  # GEMSEO is not typed.
    """The aerodynamics of the wing, computed by the normal model."""

    def __init__(self) -> None:
        """Create the discipline with its inputs and outputs."""
        super().__init__(name="Aero")
        self.io.input_grammar.update_from_names(["area", "span", "weight", "camber"])
        self.io.output_grammar.update_from_names(["drag", "load_max"])
        self.default_input_data.update(
            {
                "area": array([30.0]),
                "span": array([15.0]),
                "weight": array([80000.0]),
                "camber": array([0.05]),
            }
        )

    def _run(self, input_data: StrKeyMapping) -> StrKeyMapping:
        return aerodynamics(
            input_data["area"],
            input_data["span"],
            input_data["weight"],
            input_data["camber"],
        )
