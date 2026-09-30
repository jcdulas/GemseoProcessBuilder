"""Fixture disciplines for the catalog tests."""

from gemseo.core.discipline import Discipline
from gemseo.problems.mdo.sellar.sellar_1 import Sellar1  # noqa: F401  (imported: ignored)
from helpers import scale

from gemseo_process_builder.runtime import component


class Wing(Discipline):
    """Compute the lift of a wing."""


@component(units={"area": "m**2", "lift": "N"}, description="Lift of a wing")
def lift(area=10.0):
    lift = scale(area)
    return lift


def not_a_component(x):
    return x
