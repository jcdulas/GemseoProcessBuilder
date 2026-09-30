import nlopt
import numpy as np
import pytest
from lso_problems import PROBLEMS
from lso_problems import Known
from lso_problems import hs21
from lso_problems import hs43
from lso_problems import rosenbrock
from scipy.optimize import minimize

from gemseo_lso.benchmarks.synthetic import LocalConstraints
from gemseo_lso.core import Optimizer
from gemseo_lso.core import Settings


def synthetic():
    return LocalConstraints(400, active_share=0.05, seed=1)


@pytest.mark.parametrize("method", ["mma", "gcmma"])
@pytest.mark.parametrize("dual_solver", ["lbfgsb", "interior_point"])
@pytest.mark.parametrize("make", [p for p in PROBLEMS if p is not hs21])
def test_known_optima(make, method, dual_solver):
    known = make()
    settings = Settings(method=method, dual_solver=dual_solver, max_iter=100)
    result = Optimizer(known.problem, settings).run()
    assert result.status == "converged"
    assert result.objective == pytest.approx(known.objective, rel=1e-3, abs=1e-6)
    assert result.x == pytest.approx(known.x, abs=5e-3)
    assert result.max_constraint <= 1e-5


@pytest.mark.parametrize(
    "make", [hs21, lambda: Known("synthetic", synthetic(), None, None)]
)
def test_mma_switches_to_gcmma_when_it_cycles(make):
    # MMA's approximations are too flat near these optima (a strong own
    # curvature, small gradients): its iterates cycle, and it switches.
    known = make()
    optimizer = Optimizer(known.problem, Settings(dual_solver="lbfgsb"))
    result = optimizer.run()
    assert result.status == "converged"
    assert optimizer.state.gcmma_since > 0
    if known.objective is not None:
        assert result.objective == pytest.approx(known.objective, abs=1e-3)
    else:
        # A KKT residual of 1e-3 places x within a few 1e-3.
        assert result.x == pytest.approx(known.problem.solution, abs=5e-3)


def test_a_precision_out_of_reach_stops_the_run():
    # Rosenbrock in a disk: GCMMA keeps oscillating by about 1e-6 near the
    # optimum; asked for a KKT residual of 1e-12, it stops once it has settled.
    settings = Settings(method="gcmma", dual_solver="lbfgsb", kkt_tolerance=1e-12)
    optimizer = Optimizer(rosenbrock().problem, settings)
    result = optimizer.run()
    assert result.status == "stalled"
    assert "stalled at" in result.message
    assert result.iterations < settings.max_iter


def test_rosenbrock_in_a_disk_as_slsqp():
    known = rosenbrock()
    problem = known.problem
    reference = minimize(
        problem._objective,
        problem.x0,
        jac=problem._objective_gradient,
        method="SLSQP",
        bounds=list(zip(problem.lower, problem.upper, strict=True)),
        constraints=[
            {
                "type": "ineq",
                "fun": lambda x: -problem._constraints(x),
                "jac": lambda x: -problem._constraint_jacobian(x),
            }
        ],
        tol=1e-12,
    )
    settings = Settings(
        method="gcmma",
        dual_solver="lbfgsb",
        xtol_rel=1e-6,
        max_iter=150,
    )
    result = Optimizer(rosenbrock().problem, settings).run()
    assert result.status in ("converged", "stalled", "xtol")
    assert result.x == pytest.approx(reference.x, abs=1e-3)


def test_as_nlopt_mma():
    known = hs43()
    problem = known.problem

    def objective(x, grad):
        if grad.size:
            grad[:] = problem._objective_gradient(x)
        return problem._objective(x)

    def constraints(result, x, grad):
        if grad.size:
            grad[:] = problem._constraint_jacobian(x)
        result[:] = problem._constraints(x)

    reference = nlopt.opt(nlopt.LD_MMA, 4)
    reference.set_lower_bounds(problem.lower)
    reference.set_upper_bounds(problem.upper)
    reference.set_min_objective(objective)
    reference.add_inequality_mconstraint(constraints, np.full(3, 1e-10))
    reference.set_xtol_rel(1e-10)
    reference.set_maxeval(300)
    x = reference.optimize(problem.x0)
    result = Optimizer(hs43().problem).run()
    assert result.x == pytest.approx(x, abs=1e-3)
