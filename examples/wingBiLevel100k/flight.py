"""Loads and Performance: the analytic disciplines of the system level."""

from gemseo.disciplines.analytic import AnalyticDiscipline


def build_loads() -> AnalyticDiscipline:
    """Create the maneuver load the wing box is sized for, from the design weight."""
    return AnalyticDiscipline({"load_max": "2.5*design_weight"}, name="Loads")


def build_performance() -> AnalyticDiscipline:
    """Create the range, the wing loading and the margin on the design weight.

    The wing box is sized for the design weight chosen by the system level; the
    weight it gives must not exceed it (``weight_margin <= 0``, relative to the
    design weight, so that the tolerance on the constraints fits it).
    """
    return AnalyticDiscipline(
        {
            "range_km": "600*weight/drag*log(1 + 20000/weight)",
            "wing_loading": "weight/area",
            "weight_margin": "weight/design_weight - 1",
        },
        name="Performance",
    )
