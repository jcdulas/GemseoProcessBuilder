"""The validation of an optimum found on the surrogates, on the normal models.

The optimum (shared and local variables) is evaluated twice, by an MDA of the
surrogates and by an MDA of the normal models; the relative gap tells whether
the surrogates can be trusted there.
"""

from dataclasses import dataclass

from aero_optimizer import AERO
from gemseo import create_mda
from gemseo.core.discipline import Discipline
from gemseo.scenarios.base_scenario import BaseScenario
from numpy import array
from performance import build_performance
from structure_optimizer import STRUCTURE

LOCAL_VARIABLES = ("camber", "thickness")
"""The variables of the sub-optimizations, at the optimum of the system."""

COMPARED = ("range_km", "wing_loading", "weight", "drag")
COUPLINGS = ("weight", "load_max")
"""The variables computed by one model and used by the other."""


@dataclass(frozen=True)
class Validation:
    """An optimum evaluated by the surrogates and by the normal models."""

    point: dict[str, float]
    surrogates: dict[str, float]
    normal: dict[str, float]

    def error(self, name: str) -> float:
        """Return the relative gap of a variable, the normal model as reference."""
        return abs(self.surrogates[name] - self.normal[name]) / abs(self.normal[name])

    def report(self) -> str:
        """Return the comparison, one variable per line."""
        point = ", ".join(f"{name}={value:.4g}" for name, value in self.point.items())
        lines = [f"Optimum: {point}"]
        for name in COMPARED:
            gap = 100 * self.error(name)
            lines.append(
                f"  {name:<13} surrogates {self.surrogates[name]:12.2f}   "
                f"normal {self.normal[name]:12.2f}   gap {gap:5.2f} %"
            )
        return "\n".join(lines)


def optimum(scenario: BaseScenario) -> dict[str, float]:
    """Return the shared variables at the optimum, and the local ones found there."""
    problem = scenario.formulation.optimization_problem
    x_opt = scenario.optimization_result.x_opt
    point = {
        name: float(value)
        for name, value in zip(problem.design_space.variable_names, x_opt, strict=True)
    }
    for name in LOCAL_VARIABLES:
        point[name] = float(problem.database.get_function_value(name, x_opt)[0])
    return point


def evaluate(
    disciplines: list[Discipline], point: dict[str, float]
) -> dict[str, float]:
    """Evaluate the wing at a point, the couplings solved by an MDA."""
    mda = create_mda("MDAChain", disciplines, tolerance=1e-10)
    results = mda.execute({name: array([value]) for name, value in point.items()})
    return {name: float(results[name][0]) for name in (*COMPARED, *COUPLINGS)}


def validate(scenario: BaseScenario) -> Validation:
    """Evaluate the optimum of a scenario on the surrogates and the normal models."""
    point = optimum(scenario)
    surrogates = [AERO.surrogate(), STRUCTURE.surrogate(), build_performance()]
    normal = [AERO.normal(), STRUCTURE.normal(), build_performance()]
    return Validation(point, evaluate(surrogates, point), evaluate(normal, point))
