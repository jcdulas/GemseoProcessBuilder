"""WingBoxOptimizer: the sub-optimization of the 50,000 skin thicknesses.

For the area, span and load the system level gives, it chooses the thickness
of the skins at each station (relative to a reference, see wing_box.py)
giving the lightest aircraft whose tip does not deflect more than allowed.
MMA uses the exact gradients; at the optimum, the deflection constraint is its
active set, and its Lagrange multiplier tells the system level how the optimal
weight moves with the load.
"""

from gemseo import create_design_space, create_scenario
from gemseo.disciplines.scenario_adapters.mdo_scenario_adapter import (
    MDOScenarioAdapter,
)

from wing_box_optimizer.wing_box import STATIONS, WingBox


def build_wing_box_optimizer() -> MDOScenarioAdapter:
    """Create the sub-optimization of the skins, as a discipline of the system.

    Its only output is its optimum, the weight: the post-optimal analysis gives
    its derivatives with respect to the inputs of the adapter.
    """
    design_space = create_design_space()
    # Bounds never reached by an optimum (the relative thicknesses stay between
    # 0.2 and 2): the post-optimal analysis of GEMSEO builds a dense matrix of
    # the active bounds, which 50,000 would overflow.
    design_space.add_variable(
        "relative_thickness",
        size=STATIONS,
        lower_bound=0.01,
        upper_bound=10.0,
        value=1.0,
    )
    scenario = create_scenario(
        [WingBox()],
        "weight",
        design_space,
        name="WingBoxOptimizer",
        formulation_name="DisciplinaryOpt",
    )
    scenario.add_constraint("deflection_margin", constraint_type="ineq")
    # 50,000 variables: no table of the design space in the log. MMA reaches
    # the optimum within 1e-5 in about 25 iterations, then dithers around the
    # constraint: 30 iterations are enough.
    scenario.set_algorithm(
        algo_name="NLOPT_MMA",
        max_iter=30,
        ftol_rel=1e-6,
        xtol_rel=1e-6,
        log_problem=False,
        enable_progress_bar=False,
    )
    return MDOScenarioAdapter(scenario, ["area", "span", "load_max"], ["weight"])
