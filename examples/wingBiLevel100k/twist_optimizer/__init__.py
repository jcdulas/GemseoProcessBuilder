"""TwistOptimizer: the sub-optimization of the 50,000 twists, on the aerodynamics.

For the area, span and weight the system level gives, it chooses the twist of
each section giving the least drag. L-BFGS-B uses the exact gradient: its
cost does not grow with the number of sections, and the bounds of the twists
are its active set.
"""

from gemseo import create_design_space, create_scenario
from gemseo.disciplines.scenario_adapters.mdo_scenario_adapter import (
    MDOScenarioAdapter,
)

from twist_optimizer.aerodynamics import STATIONS, Aerodynamics


def build_twist_optimizer() -> MDOScenarioAdapter:
    """Create the sub-optimization of the twist, as a discipline of the system.

    Its only output is its optimum, the drag: the post-optimal analysis gives
    its derivatives with respect to the inputs of the adapter.
    """
    design_space = create_design_space()
    # Bounds never reached by an optimum: the post-optimal analysis of GEMSEO
    # builds a dense matrix of the active bounds, which 50,000 would overflow.
    design_space.add_variable(
        "twist", size=STATIONS, lower_bound=-90.0, upper_bound=90.0, value=0.0
    )
    scenario = create_scenario(
        [Aerodynamics()],
        "drag",
        design_space,
        name="TwistOptimizer",
        formulation_name="DisciplinaryOpt",
    )
    # 50,000 variables: no table of the design space in the log.
    scenario.set_algorithm(
        algo_name="L-BFGS-B",
        max_iter=200,
        ftol_rel=1e-10,
        xtol_rel=1e-10,
        log_problem=False,
        enable_progress_bar=False,
    )
    return MDOScenarioAdapter(scenario, ["area", "span", "weight"], ["drag"])
