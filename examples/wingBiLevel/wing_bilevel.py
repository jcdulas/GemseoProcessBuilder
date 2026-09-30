"""Wing sizing in bi-level, on surrogates checked by the normal models.

The wing sizing of wing_sizing.py, in bi-level: the system level chooses the
area and the span of the wing to maximize the range, while the aerodynamics
chooses the camber of the airfoil and the structure the thickness of the wing
box.

The files follow the graph of the study: SystemOptimizer here, AeroOptimizer
and StructureOptimizer in their folders, each with its normal model and the
surrogate trained on it (duo.py), and Performance. The optimization loops on
the surrogates; its optimum is validated on the normal models (validation.py),
and while the range they give differs by more than 1 %, the surrogates learn
the normal models around the optimum and the optimization runs again.

Run it with: python wing_bilevel.py
"""

from aero_optimizer import AERO, build_aero_optimizer
from gemseo import configure_logger, create_design_space, create_scenario
from gemseo.algos.design_space import DesignSpace
from gemseo.scenarios.base_scenario import BaseScenario
from performance import build_performance
from structure_optimizer import STRUCTURE, build_structure_optimizer
from validation import validate

TOLERANCE = 0.01
"""The largest relative gap on the range between the surrogates and the models."""

MAX_ROUNDS = 4


def build_design_space() -> DesignSpace:
    """Define the shape of the wing, chosen by the system level."""
    design_space = create_design_space()
    design_space.add_variable("area", lower_bound=10.0, upper_bound=60.0, value=30.0)
    design_space.add_variable("span", lower_bound=8.0, upper_bound=30.0, value=15.0)
    return design_space


def build_system_optimizer() -> BaseScenario:
    """Set up the system level: the two sub-optimizations and the performance."""
    scenario = create_scenario(
        [build_aero_optimizer(), build_structure_optimizer(), build_performance()],
        "range_km",
        build_design_space(),
        name="SystemOptimizer",
        maximize_objective=True,
        formulation_name="BiLevel",
        apply_cstr_tosub_scenarios=False,
    )
    scenario.add_constraint("wing_loading", constraint_type="ineq", value=3000.0)
    return scenario


def optimize_and_validate() -> None:
    """Optimize on the surrogates until the normal models confirm the optimum."""
    configure_logger()
    for round_number in range(1, MAX_ROUNDS + 1):
        scenario = build_system_optimizer()
        scenario.execute(algo_name="NLOPT_COBYLA", max_iter=60)
        validation = validate(scenario)
        print(f"Round {round_number}. {validation.report()}")
        if validation.error("range_km") <= TOLERANCE:
            print("The normal models confirm the optimum found on the surrogates.")
            return
        # Not accurate enough there: learn the normal models around the optimum,
        # with the couplings the normal models give there.
        around = {**validation.point, **validation.normal}
        AERO.enrich(around)
        STRUCTURE.enrich(around)
    print(f"The surrogates are still not accurate enough after {MAX_ROUNDS} rounds.")


if __name__ == "__main__":
    optimize_and_validate()
