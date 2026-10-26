"""Sellar, its scenario of a class of its own (as gemseo_nastran's bay scenarios)."""
from gemseo import configure_logger, create_design_space, create_discipline
from gemseo.scenarios.mdo_scenario import MDOScenario
from numpy import array


class StoppedScenario(MDOScenario):
    """An optimization with a stopping rule of its own."""


configure_logger()
disciplines = create_discipline(["Sellar1", "Sellar2", "SellarSystem"])
design_space = create_design_space()
design_space.add_variable("x_1", lower_bound=0.0, upper_bound=10.0, value=1.0)
design_space.add_variable("x_shared", 2, lower_bound=(-10, 0.0), upper_bound=(10.0, 10.0), value=array([4.0, 3.0]))
scenario = StoppedScenario(disciplines, "obj", design_space, name="Stopped", formulation_name="MDF")
scenario.add_constraint("c_1", constraint_type="ineq")
scenario.execute(algo_name="SLSQP", max_iter=10)
