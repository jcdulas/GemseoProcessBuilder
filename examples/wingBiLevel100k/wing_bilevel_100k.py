"""Wing sizing in bi-level with 100,000 variables, on gradients and sensitivities.

The bi-level wing sizing of wingBiLevel/, at scale: the twist of 50,000
sections of the wing and the skin thickness of 50,000 stations of its box.

- The system level chooses the area and the span of the wing, and the weight
  the wing box is designed for, to maximize the range; SLSQP, an active-set
  method, handles its constraints.
- TwistOptimizer (twist_optimizer/) chooses the 50,000 twists giving the
  least drag, with L-BFGS-B.
- WingBoxOptimizer (wing_box_optimizer/) chooses the 50,000 thicknesses giving
  the lightest aircraft whose tip deflection stays within its limit, with MMA.

Every gradient is exact, and costs as much as the functions: the optimizers
handle 50,000 variables in a few seconds. The sub-optimizations give the
system the derivatives of their optima, computed by the post-optimal analysis
on their active sets (sensitivities.py): the system level uses gradients too,
and converges in a few iterations.

Run it with: python wing_bilevel_100k.py
"""

from time import perf_counter

from flight import build_loads, build_performance
from gemseo import configure_logger, create_design_space, create_scenario
from gemseo.algos.design_space import DesignSpace
from gemseo.scenarios.base_scenario import BaseScenario
from sensitivities import report
from twist_optimizer import build_twist_optimizer
from wing_box_optimizer import build_wing_box_optimizer


def build_design_space() -> DesignSpace:
    """Define the wing and the weight the wing box is designed for."""
    design_space = create_design_space()
    design_space.add_variable("area", lower_bound=25.0, upper_bound=50.0, value=30.0)
    design_space.add_variable("span", lower_bound=10.0, upper_bound=18.0, value=15.0)
    design_space.add_variable(
        "design_weight", lower_bound=65000.0, upper_bound=110000.0, value=90000.0
    )
    return design_space


def build_system_optimizer() -> BaseScenario:
    """Set up the system level on top of the two sub-optimizations.

    The wing box is sized for the design weight; the aerodynamics fly the
    weight it gives. No loop: each evaluation runs each sub-optimization once,
    and the constraint on the weight margin makes the two weights agree.
    """
    scenario = create_scenario(
        [
            build_loads(),
            build_wing_box_optimizer(),
            build_twist_optimizer(),
            build_performance(),
        ],
        "range_km",
        build_design_space(),
        name="SystemOptimizer",
        maximize_objective=True,
        formulation_name="MDF",
    )
    scenario.add_constraint("wing_loading", constraint_type="ineq", value=3000.0)
    scenario.add_constraint("weight_margin", constraint_type="ineq")
    return scenario


def optimize() -> None:
    """Run the bi-level optimization and describe its optimum."""
    configure_logger()
    start = perf_counter()
    scenario = build_system_optimizer()
    # The sub-optimizations are converged to about 1e-6: so is the system level.
    scenario.execute(algo_name="SLSQP", max_iter=50, ftol_rel=1e-6)
    print(report(scenario, perf_counter() - start))


if __name__ == "__main__":
    optimize()
