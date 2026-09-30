"""Sobieski bi-level study in several files.

The bi-level optimization of the Sobieski supersonic business jet, written
by hand for GEMSEO 6 with a component of every kind.

The system level maximizes the range of the aircraft by changing the shared
variables (wing, altitude, Mach number...). For each of its iterations, three
sub-optimizations improve the local variables of the propulsion, the
aerodynamics and the structure (local_problems.py). The economics of each
design are followed along (economics.py): fuel, CO2, noise, maintenance and
operating cost.

Run it with: python demo_bilevel.py
"""

from economics import build_economics
from gemseo import configure_logger, create_design_space, create_scenario
from gemseo.algos.design_space import DesignSpace
from gemseo.problems.mdo.sobieski.disciplines import SobieskiMission
from gemseo.scenarios.base_scenario import BaseScenario
from local_problems import build_sub_scenarios


def build_shared_design_space() -> DesignSpace:
    """Define the variables shared by the disciplines, optimized at system level."""
    design_space = create_design_space()
    design_space.add_variable(
        "x_shared",
        size=6,
        lower_bound=[0.01, 30000.0, 1.4, 2.5, 40.0, 500.0],
        upper_bound=[0.09, 60000.0, 1.8, 8.5, 70.0, 1500.0],
        value=[0.05, 45000.0, 1.6, 5.5, 55.0, 1000.0],
    )
    return design_space


def build_system_scenario() -> BaseScenario:
    """Set up the system level: sub-optimizations, mission and economics."""
    scenario = create_scenario(
        [*build_sub_scenarios(), SobieskiMission(), build_economics()],
        "y_4",
        build_shared_design_space(),
        name="SystemOptimizer",
        maximize_objective=True,
        formulation_name="BiLevel",
        apply_cstr_tosub_scenarios=False,
    )
    for constraint in ("g_1", "g_2", "g_3"):
        scenario.add_constraint(constraint, constraint_type="ineq")
    # Followed at each iteration, not optimized.
    for observable in ("cost", "co2", "noise_db", "maintenance"):
        scenario.add_observable(observable)
    return scenario


def main() -> None:
    """Run the bi-level optimization and print the best design."""
    configure_logger()
    scenario = build_system_scenario()
    scenario.execute(algo_name="COBYQA", max_iter=20)
    result = scenario.optimization_result
    print(f"Range: {-result.f_opt:.1f} nm")
    print(f"Shared variables: {result.x_opt}")


if __name__ == "__main__":
    main()
