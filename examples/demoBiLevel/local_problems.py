"""The sub-optimizations of the bi-level study, one per discipline.

Each discipline of the aircraft improves its own design variables, for the
shared variables the system level gives it.
"""

from dataclasses import dataclass

from gemseo import create_design_space, create_scenario
from gemseo.core.discipline import Discipline
from gemseo.problems.mdo.sobieski.disciplines import (
    SobieskiAerodynamics,
    SobieskiPropulsion,
    SobieskiStructure,
)
from gemseo.scenarios.base_scenario import BaseScenario


@dataclass(frozen=True)
class LocalProblem:
    """A sub-optimization: a discipline, its own variables, its own goal."""

    name: str
    discipline: type[Discipline]
    variable: str
    lower_bound: list[float]
    upper_bound: list[float]
    value: list[float]
    objective: str
    constraint: str
    maximize: bool = False

    def build_scenario(self) -> BaseScenario:
        """Create the scenario optimizing the local variables of the discipline."""
        design_space = create_design_space()
        design_space.add_variable(
            self.variable,
            size=len(self.value),
            lower_bound=self.lower_bound,
            upper_bound=self.upper_bound,
            value=self.value,
        )
        scenario = create_scenario(
            [self.discipline()],
            self.objective,
            design_space,
            name=self.name,
            maximize_objective=self.maximize,
            formulation_name="DisciplinaryOpt",
        )
        scenario.add_constraint(self.constraint, constraint_type="ineq")
        # A sub-optimization runs with this algorithm each time the system
        # level executes it.
        scenario.set_algorithm(algo_name="SLSQP", max_iter=30)
        return scenario


LOCAL_PROBLEMS = (
    # The throttle, to minimize the specific fuel consumption.
    LocalProblem(
        name="PropulsionOptimizer",
        discipline=SobieskiPropulsion,
        variable="x_3",
        lower_bound=[0.1],
        upper_bound=[1.0],
        value=[0.5],
        objective="y_34",
        constraint="g_3",
    ),
    # The skin friction, to maximize the lift over drag ratio.
    LocalProblem(
        name="AerodynamicsOptimizer",
        discipline=SobieskiAerodynamics,
        variable="x_2",
        lower_bound=[0.75],
        upper_bound=[1.25],
        value=[1.0],
        objective="y_24",
        constraint="g_2",
        maximize=True,
    ),
    # The taper ratio and the wing box section, to maximize the weight ratio.
    LocalProblem(
        name="StructureOptimizer",
        discipline=SobieskiStructure,
        variable="x_1",
        lower_bound=[0.1, 0.75],
        upper_bound=[0.4, 1.25],
        value=[0.25, 1.0],
        objective="y_11",
        constraint="g_1",
        maximize=True,
    ),
)


def build_sub_scenarios() -> list[BaseScenario]:
    """Create the three sub-optimizations, in the order of the problems."""
    return [problem.build_scenario() for problem in LOCAL_PROBLEMS]
