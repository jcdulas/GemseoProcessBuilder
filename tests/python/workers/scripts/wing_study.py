"""A study written by hand: its own function and class, a value set later."""

from gemseo import create_design_space, create_scenario
from gemseo.core.discipline import Discipline
from gemseo.disciplines.analytic import AnalyticDiscipline
from gemseo.disciplines.auto_py import AutoPyDiscipline
from numpy import array


def wing_area(span=10.0, chord=2.0):
    area = span * chord
    return area


class Lift(Discipline):
    def __init__(self, density=1.2):
        super().__init__()
        self.density = density
        self.io.input_grammar.update_from_names(["area", "speed"])
        self.io.output_grammar.update_from_names(["lift"])
        self.io.input_grammar.defaults = {"area": array([20.0]), "speed": array([50.0])}

    def _run(self, input_data):
        return {"lift": 0.5 * self.density * input_data["speed"] ** 2 * input_data["area"]}


area = AutoPyDiscipline(wing_area)
lift = Lift(density=1.1)
cost = AnalyticDiscipline({"cost": "100*span + 50*chord"}, name="Cost")
cost.default_input_data.update({"chord": array([3.0])})

space = create_design_space()
space.add_variable("span", lower_bound=5.0, upper_bound=20.0, value=10.0)
scenario = create_scenario([area, lift, cost], "cost", space, formulation_name="MDF", name="Sizing")
scenario.add_constraint("lift", constraint_type="ineq", value=30000.0, positive=True)
scenario.execute(algo_name="NLOPT_COBYLA", max_iter=50)
raise RuntimeError("The study ran: the reader should have stopped it.")
