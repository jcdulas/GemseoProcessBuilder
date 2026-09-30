import time

import numpy as np
from gemseo.algos.design_space import DesignSpace
from gemseo.algos.optimization_problem import OptimizationProblem
from gemseo.core.mdo_functions.mdo_function import MDOFunction
from pilot_samples import sellar

from gemseo_claude_pilot.context import build_context
from gemseo_claude_pilot.context import estimate_tokens
from gemseo_claude_pilot.context import render
from gemseo_claude_pilot.snapshots import snapshot_history
from gemseo_claude_pilot.snapshots import snapshot_problem


def snapshots(scenario):
    problem = scenario.formulation.optimization_problem
    snapshot = snapshot_problem(
        problem, "SLSQP", 100, {"max_iter": 5}, formulation="MDF"
    )
    return problem, snapshot, snapshot_history(problem, snapshot)


def test_problem_of_sellar():
    _, snapshot, _ = snapshots(sellar())
    assert [variable.name for variable in snapshot.variables] == [
        "x_1",
        "x_2",
        "x_shared",
    ]
    assert snapshot.design_size == 4
    assert snapshot.variables[2].upper.tolist() == [10.0, 10.0]
    assert (snapshot.objective, snapshot.minimize) == ("obj", True)
    assert [(item.name, item.type) for item in snapshot.constraints] == [
        ("c_1", "ineq"),
        ("c_2", "ineq"),
    ]
    assert snapshot.gradients == "exact"
    assert snapshot.settings == {"max_iter": 5}


def test_history_of_sellar():
    problem, _, history = snapshots(sellar())
    database = problem.database
    assert history.n_evaluations == len(database)
    assert np.allclose(history.objective, database.get_function_history("obj"))
    best = history.best_index
    assert np.allclose(history.best_x, database.get_x_vect_history()[best])
    assert history.feasible[best]
    assert history.step[0] == 0
    assert history.recent_x.shape == (len(database), 4)
    assert history.best_gradient.shape == (4,)
    assert set(history.constraints) == {"c_1", "c_2"}


def test_maximization_keeps_the_sign_of_the_user():
    problem, snapshot, history = snapshots(sellar(max_iter=2, maximize=True))
    assert snapshot.minimize is False
    assert snapshot.standardized_objective == "-obj"
    assert np.allclose(
        history.objective, -problem.database.get_function_history("-obj")
    )


def test_large_design_space_is_fast():
    space = DesignSpace()
    space.add_variable(
        "thickness", 100_000, lower_bound=0.0, upper_bound=1.0, value=0.5
    )
    problem = OptimizationProblem(space)
    problem.objective = MDOFunction(lambda x: float(np.sum(x**2)), "weight")
    rng = np.random.default_rng(3)
    for _ in range(5):
        x = rng.random(100_000)
        problem.database.store(x, {"weight": float(np.sum(x**2)), "@weight": 2 * x})

    start = time.perf_counter()
    snapshot = snapshot_problem(problem, "L-BFGS-B", 1000)
    history = snapshot_history(problem, snapshot)
    context = build_context(snapshot, history)
    duration = time.perf_counter() - start

    assert duration < 0.5
    assert estimate_tokens(render(context)) < 8_000
    variable = context["problem"]["design_variables"][0]
    assert variable["size"] == 100_000
    assert "share_at_lower_bound" in variable
    important = context["problem"]["most_important_components"]
    assert len(important) == 20
    assert important[0]["ranked_by"] == "gradient times range"
