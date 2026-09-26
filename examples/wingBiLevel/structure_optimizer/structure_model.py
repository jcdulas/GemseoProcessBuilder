"""The normal structural model of the wing.

It stands for a costly structural solver: the weight of the aircraft, whose
wing box must carry the load of the maneuver. The thickness of the wing box is
its own design variable: a thick box resists bending with less material, but
its skins weigh more.
"""

from gemseo.core.discipline import Discipline
from gemseo.typing import StrKeyMapping
from numpy import array, float64
from numpy.typing import NDArray


def structure(
    area: NDArray[float64],
    span: NDArray[float64],
    load_max: NDArray[float64],
    thickness: NDArray[float64],
) -> dict[str, NDArray[float64]]:
    """Compute the weight of the aircraft.

    Args:
        area: The area of the wing, in m2.
        span: The span of the wing, in m.
        load_max: The maximum load the wing carries, in N.
        thickness: The thickness of the wing box, relative to the chord.

    Returns:
        The weight of the aircraft, in N.

    """
    skins = 500.0 * area * (0.6 + 3.5 * thickness)
    bending = 0.006 * load_max * span**2 / area * (0.12 / thickness)
    return {"weight": 50000.0 + skins + bending}


class StructureModel(Discipline):  # type: ignore[misc]  # GEMSEO is not typed.
    """The weight of the aircraft, computed by the normal model."""

    def __init__(self) -> None:
        """Create the discipline with its inputs and outputs."""
        super().__init__(name="Structure")
        self.io.input_grammar.update_from_names(
            ["area", "span", "load_max", "thickness"]
        )
        self.io.output_grammar.update_from_names(["weight"])
        self.default_input_data.update(
            {
                "area": array([30.0]),
                "span": array([15.0]),
                "load_max": array([200000.0]),
                "thickness": array([0.12]),
            }
        )

    def _run(self, input_data: StrKeyMapping) -> StrKeyMapping:
        return structure(
            input_data["area"],
            input_data["span"],
            input_data["load_max"],
            input_data["thickness"],
        )
