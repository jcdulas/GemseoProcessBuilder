"""Performance: the range of the aircraft and the loading of its wing."""

from gemseo.disciplines.analytic import AnalyticDiscipline


def build_performance() -> AnalyticDiscipline:
    """Create the range (Breguet) and the wing loading, from the weight and drag."""
    return AnalyticDiscipline(
        {
            "range_km": "600*weight/drag*log(1 + 20000/weight)",
            "wing_loading": "weight/area",
        },
        name="Performance",
    )
