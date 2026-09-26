"""AeroOptimizer: the sub-optimization of the camber, on the aerodynamics.

For the area, span and weight the system level gives, it chooses the camber
of the airfoil giving the least drag.
"""

from duo import ModelDuo
from gemseo import create_design_space, create_scenario
from gemseo.scenarios.base_scenario import BaseScenario

from aero_optimizer.aero_model import AeroModel, aerodynamics

AERO = ModelDuo(
    name="Aero",
    model=AeroModel,
    physics=aerodynamics,
    bounds={
        "area": (10.0, 60.0),
        "span": (8.0, 30.0),
        "weight": (50000.0, 200000.0),
        "camber": (0.0, 0.12),
    },
    outputs=("drag", "load_max"),
)
"""The aerodynamics: the normal model and its surrogate."""


def build_aero_optimizer() -> BaseScenario:
    """Create the sub-optimization of the camber, on the surrogate."""
    design_space = create_design_space()
    design_space.add_variable("camber", lower_bound=0.0, upper_bound=0.12, value=0.05)
    scenario = create_scenario(
        [AERO.surrogate()],
        "drag",
        design_space,
        name="AeroOptimizer",
        formulation_name="DisciplinaryOpt",
    )
    scenario.set_algorithm(algo_name="SLSQP", max_iter=30)
    return scenario
