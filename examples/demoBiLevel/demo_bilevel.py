"""Bi-level optimization of the Sobieski supersonic business jet, with GEMSEO 6.

The system level maximizes the range of the aircraft by changing the shared
variables (wing, altitude, Mach number...). For each of its iterations, three
sub-optimizations improve the local variables of the propulsion, the
aerodynamics and the structure.

Run it with: python demo_bilevel.py
"""

from gemseo import configure_logger, create_design_space, create_scenario
from gemseo.problems.mdo.sobieski.disciplines import (
    SobieskiAerodynamics,
    SobieskiMission,
    SobieskiPropulsion,
    SobieskiStructure,
)

configure_logger()

# Propulsion: the throttle, to minimize the fuel consumption.
propulsion_space = create_design_space()
propulsion_space.add_variable("x_3", lower_bound=0.1, upper_bound=1.0, value=0.5)
propulsion_scenario = create_scenario(
    [SobieskiPropulsion()],
    "y_34",
    propulsion_space,
    name="PropulsionOptimizer",
    formulation_name="DisciplinaryOpt",
)
propulsion_scenario.add_constraint("g_3", constraint_type="ineq")
propulsion_scenario.set_algorithm(algo_name="SLSQP", max_iter=30)

# Aerodynamics: the skin friction, to maximize the lift over drag ratio.
aerodynamics_space = create_design_space()
aerodynamics_space.add_variable("x_2", lower_bound=0.75, upper_bound=1.25, value=1.0)
aerodynamics_scenario = create_scenario(
    [SobieskiAerodynamics()],
    "y_24",
    aerodynamics_space,
    name="AerodynamicsOptimizer",
    maximize_objective=True,
    formulation_name="DisciplinaryOpt",
)
aerodynamics_scenario.add_constraint("g_2", constraint_type="ineq")
aerodynamics_scenario.set_algorithm(algo_name="SLSQP", max_iter=30)

# Structure: the wing taper ratio and box section, to maximize the weight ratio.
structure_space = create_design_space()
structure_space.add_variable(
    "x_1",
    size=2,
    lower_bound=[0.1, 0.75],
    upper_bound=[0.4, 1.25],
    value=[0.25, 1.0],
)
structure_scenario = create_scenario(
    [SobieskiStructure()],
    "y_11",
    structure_space,
    name="StructureOptimizer",
    maximize_objective=True,
    formulation_name="DisciplinaryOpt",
)
structure_scenario.add_constraint("g_1", constraint_type="ineq")
structure_scenario.set_algorithm(algo_name="SLSQP", max_iter=30)

# System: the shared variables, to maximize the range.
system_space = create_design_space()
system_space.add_variable(
    "x_shared",
    size=6,
    lower_bound=[0.01, 30000.0, 1.4, 2.5, 40.0, 500.0],
    upper_bound=[0.09, 60000.0, 1.8, 8.5, 70.0, 1500.0],
    value=[0.05, 45000.0, 1.6, 5.5, 55.0, 1000.0],
)
system_scenario = create_scenario(
    [propulsion_scenario, aerodynamics_scenario, structure_scenario, SobieskiMission()],
    "y_4",
    system_space,
    name="SystemOptimizer",
    maximize_objective=True,
    formulation_name="BiLevel",
    apply_cstr_tosub_scenarios=False,
)
system_scenario.add_constraint("g_1", constraint_type="ineq")
system_scenario.add_constraint("g_2", constraint_type="ineq")
system_scenario.add_constraint("g_3", constraint_type="ineq")
system_scenario.execute(algo_name="COBYQA", max_iter=20)

print("Range:", -system_scenario.optimization_result.f_opt)
