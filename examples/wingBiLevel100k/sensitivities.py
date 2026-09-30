"""The active sets and the sensitivities at the optimum of each level.

At the optimum of the system, the Lagrange multipliers of each optimization
are computed on its active set: the constraints and bounds it presses
against. The post-optimal analysis of a sub-optimization uses them to give
the system the derivatives of its optimum:

    d optimum / d input = d objective / d input + multipliers . d active / d input

This is what lets the system level use gradients, and converge in a few
iterations, although each of its evaluations solves two optimizations of
50,000 variables.
"""

from gemseo.algos.lagrange_multipliers import LagrangeMultipliers
from gemseo.algos.optimization_problem import OptimizationProblem
from gemseo.disciplines.scenario_adapters.mdo_scenario_adapter import (
    MDOScenarioAdapter,
)
from gemseo.scenarios.base_scenario import BaseScenario
from numpy import float64
from numpy.typing import NDArray


def active_set(problem: OptimizationProblem, x: NDArray[float64]) -> str:
    """Describe the active set of a problem at a point, with its multipliers."""
    lagrange = LagrangeMultipliers(problem)
    lagrange.compute(x, problem.tolerances.inequality)
    multipliers = lagrange.get_multipliers_arrays()
    constraints = [
        f"{name} (multiplier {float(values[0]):.4g})"
        for kind in (lagrange.INEQUALITY, lagrange.EQUALITY)
        for name, values in multipliers[kind].items()
        if name in lagrange.active_ineq_names + lagrange.active_eq_names
    ]
    bounds = len(lagrange.active_lb_names) + len(lagrange.active_ub_names)
    active = ", ".join(constraints) if constraints else "no constraint"
    return f"{active}; {bounds} of {x.size} bounds"


def report(scenario: BaseScenario, seconds: float) -> str:
    """Describe the optimum: its values, active sets and sensitivities."""
    problem = scenario.formulation.optimization_problem
    result = scenario.optimization_result
    names = problem.design_space.variable_names
    values = zip(names, result.x_opt, strict=True)
    # An iteration of SLSQP computes the gradient; its line search does not.
    gradient = f"@{problem.objective.name}"
    iterations = sum(gradient in outputs for outputs in problem.database.values())
    lines = [
        f"SystemOptimizer: {iterations} iterations ({len(problem.database)} "
        f"evaluations) in {seconds:.0f} s, range {-result.f_opt:.1f} km",
        "  " + ", ".join(f"{name} {value:.6g}" for name, value in values),
        # Computing it evaluates the study at the optimum, with its derivatives.
        f"  active set: {active_set(problem, result.x_opt)}",
    ]
    for discipline in scenario.formulation.disciplines:
        if not isinstance(discipline, MDOScenarioAdapter):
            continue
        sub_problem = discipline.scenario.formulation.optimization_problem
        x = sub_problem.design_space.get_current_value()
        (output,) = discipline.jac
        derivatives = ", ".join(
            f"d/d {name} {float(value[0, 0]):.4g}"
            for name, value in sorted(discipline.jac[output].items())
        )
        lines += [
            f"{discipline.scenario.name}: {x.size} variables",
            f"  active set: {active_set(sub_problem, x)}",
            f"  sensitivities of the optimal {output}: {derivatives}",
        ]
    return "\n".join(lines)
