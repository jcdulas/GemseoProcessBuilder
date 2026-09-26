"""Sellar, as in GEMSEO's tutorials."""
from gemseo import configure_logger, create_design_space, create_discipline, create_scenario
from numpy import array

configure_logger()
disciplines = create_discipline(["Sellar1", "Sellar2", "SellarSystem"])
design_space = create_design_space()
design_space.add_variable("x_1", lower_bound=0.0, upper_bound=10.0, value=1.0)
design_space.add_variable("x_shared", 2, lower_bound=(-10, 0.0), upper_bound=(10.0, 10.0), value=array([4.0, 3.0]))
scenario = create_scenario(disciplines, "obj", design_space, formulation_name="MDF")
scenario.add_constraint("c_1", constraint_type="ineq")
scenario.add_constraint("c_2", constraint_type="ineq", value=0.5, positive=True)
scenario.add_observable("y_1")
scenario.execute(algo_name="SLSQP", max_iter=10)
scenario.post_process(post_name="OptHistoryView", save=True, show=False)
print("after the study")
