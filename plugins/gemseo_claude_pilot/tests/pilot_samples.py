"""Problems and histories used by the tests of the copilot plugin."""

from collections.abc import Sequence
from functools import cache
from typing import Any

import numpy as np
from gemseo import create_design_space
from gemseo import create_discipline
from gemseo import create_scenario
from gemseo.problems.mdo.sellar.sellar_design_space import SellarDesignSpace

from gemseo_claude_pilot.snapshots import Constraint
from gemseo_claude_pilot.snapshots import HistorySnapshot
from gemseo_claude_pilot.snapshots import ProblemSnapshot
from gemseo_claude_pilot.snapshots import Variable


def variable(
    name: str,
    size: int = 1,
    lower: float = 0.0,
    upper: float = 10.0,
    value: float | None = None,
    integer: bool = False,
) -> Variable:
    return Variable(
        name=name,
        size=size,
        lower=np.full(size, lower),
        upper=np.full(size, upper),
        value=None if value is None else np.full(size, value),
        integer=integer,
    )


def problem(
    variables: Sequence[Variable] | None = None,
    constraints: Sequence[Constraint] = (),
    **settings: Any,
) -> ProblemSnapshot:
    """A problem on ``x`` (2 components in [0, 10], at 5) minimizing ``f``."""
    return ProblemSnapshot(
        variables=tuple(variables or (variable("x", 2, value=5.0),)),
        objective="f",
        standardized_objective="f",
        algo_name=settings.pop("algo_name", "SLSQP"),
        evaluation_budget=settings.pop("evaluation_budget", 100),
        constraints=tuple(constraints),
        **settings,
    )


def ineq(name: str) -> Constraint:
    return Constraint(name, name, "ineq")


def eq(name: str) -> Constraint:
    return Constraint(name, name, "eq")


def history(
    objective: Sequence[float],
    violation: Sequence[float] | None = None,
    recent_x: Sequence[Sequence[float]] | None = None,
    design_size: int = 2,
    minimize: bool = True,
) -> HistorySnapshot:
    """A history of the objective, feasible unless told otherwise."""
    n = len(objective)
    points = np.asarray(
        recent_x if recent_x is not None else np.full((1, design_size), 0.5)
    )
    return HistorySnapshot(
        objective=np.asarray(objective, dtype=float),
        violation=np.zeros(n) if violation is None else np.asarray(violation, float),
        step=np.full(n, 0.1),
        recent_x=points,
        first_x=np.full(design_size, 5.0),
        best_x=np.full(design_size, 5.0),
        minimize=minimize,
    )


@cache
def sellar(max_iter: int = 5, maximize: bool = False) -> Any:
    """The Sellar problem in MDF, solved by SLSQP for a few iterations.

    Solved once per setting, at collection time (see conftest.py): the tests
    only read the scenario, and running one from a test could exceed the
    one-second limit when GEMSEO starts the threads of its MDA.
    """
    disciplines = create_discipline(["Sellar1", "Sellar2", "SellarSystem"])
    scenario = create_scenario(
        disciplines,
        "obj",
        SellarDesignSpace(),
        formulation_name="MDF",
        maximize_objective=maximize,
    )
    scenario.add_constraint("c_1", constraint_type="ineq")
    scenario.add_constraint("c_2", constraint_type="ineq")
    scenario.execute(algo_name="SLSQP", max_iter=max_iter)
    return scenario


def rosenbrock() -> Any:
    """A constrained Rosenbrock scenario, analytic and without MDA: fast to run."""
    discipline = create_discipline(
        "AnalyticDiscipline",
        expressions={"f": "(1 - x)**2 + 100*(y - x**2)**2", "g": "x + y - 1.5"},
        name="Rosenbrock",
    )
    space = create_design_space()
    space.add_variable("x", lower_bound=-2.0, upper_bound=2.0, value=-1.5)
    space.add_variable("y", lower_bound=-1.0, upper_bound=3.0, value=2.5)
    scenario = create_scenario(
        [discipline], "f", space, formulation_name="DisciplinaryOpt"
    )
    scenario.add_constraint("g", constraint_type="ineq")
    return scenario


def rosenbrock_doe() -> Any:
    """The Rosenbrock function sampled by a DOE."""
    discipline = create_discipline(
        "AnalyticDiscipline",
        expressions={"f": "(1 - x)**2 + 100*(y - x**2)**2"},
        name="Rosenbrock",
    )
    space = create_design_space()
    space.add_variable("x", lower_bound=-2.0, upper_bound=2.0, value=0.0)
    space.add_variable("y", lower_bound=-1.0, upper_bound=3.0, value=0.0)
    return create_scenario(
        [discipline],
        "f",
        space,
        formulation_name="DisciplinaryOpt",
        scenario_type="DOE",
    )


def small_bilevel() -> Any:
    """A BiLevel study: a sub-optimization of a local variable on each side,
    under a system optimization of the shared one."""
    left = create_discipline(
        "AnalyticDiscipline", expressions={"y1": "(x1 - z)**2 + 1"}, name="Left"
    )
    right = create_discipline(
        "AnalyticDiscipline", expressions={"y2": "(x2 + z)**2 + 1"}, name="Right"
    )
    system = create_discipline(
        "AnalyticDiscipline", expressions={"f": "y1 + y2 + (z - 1)**2"}, name="System"
    )
    subs = []
    for name, discipline, local, objective in (
        ("LeftOptimizer", left, "x1", "y1"),
        ("RightOptimizer", right, "x2", "y2"),
    ):
        space = create_design_space()
        space.add_variable(local, lower_bound=-3.0, upper_bound=3.0, value=0.0)
        sub = create_scenario(
            [discipline],
            objective,
            space,
            formulation_name="DisciplinaryOpt",
            name=name,
        )
        sub.set_algorithm(algo_name="SLSQP", max_iter=10)
        subs.append(sub)
    space = create_design_space()
    space.add_variable("z", lower_bound=-2.0, upper_bound=2.0, value=-1.5)
    return create_scenario([*subs, system], "f", space, formulation_name="BiLevel")
