"""StructureOptimizer: the sub-optimization of the wing box, on the structure.

For the area, span and load the system level gives, it chooses the thickness
of the wing box giving the lightest aircraft.
"""

from duo import ModelDuo
from gemseo import create_design_space, create_scenario
from gemseo.scenarios.base_scenario import BaseScenario

from structure_optimizer.structure_model import StructureModel, structure

STRUCTURE = ModelDuo(
    name="Structure",
    model=StructureModel,
    physics=structure,
    bounds={
        "area": (10.0, 60.0),
        "span": (8.0, 30.0),
        "load_max": (125000.0, 500000.0),
        "thickness": (0.08, 0.2),
    },
    outputs=("weight",),
)
"""The structure: the normal model and its surrogate."""


def build_structure_optimizer() -> BaseScenario:
    """Create the sub-optimization of the thickness, on the surrogate."""
    design_space = create_design_space()
    design_space.add_variable(
        "thickness", lower_bound=0.08, upper_bound=0.2, value=0.12
    )
    scenario = create_scenario(
        [STRUCTURE.surrogate()],
        "weight",
        design_space,
        name="StructureOptimizer",
        formulation_name="DisciplinaryOpt",
    )
    scenario.set_algorithm(algo_name="SLSQP", max_iter=30)
    return scenario
