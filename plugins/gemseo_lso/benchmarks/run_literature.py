"""The solver on problems of the literature, against their published optima.

Trusses (10, 25 and 72 bars), Svanberg's beam and three Hock-Schittkowski
problems; SLSQP (SciPy) is the independent reference on the small ones.

    python plugins/gemseo_lso/benchmarks/run_literature.py
"""

import time
import warnings

import numpy as np
from scipy.optimize import minimize

from gemseo_lso.benchmarks.literature.classics import beam
from gemseo_lso.benchmarks.literature.classics import hs71
from gemseo_lso.benchmarks.literature.classics import hs100
from gemseo_lso.benchmarks.literature.classics import hs113
from gemseo_lso.benchmarks.literature.trusses import seventy_two_bar
from gemseo_lso.benchmarks.literature.trusses import ten_bar
from gemseo_lso.benchmarks.literature.trusses import twenty_five_bar
from gemseo_lso.core import Optimizer
from gemseo_lso.core import Settings

warnings.simplefilter("ignore")


def reference(problem):
    """The optimum found by SLSQP, from the same start."""
    everything = np.arange(problem.values(problem.x0)[1].size)
    constraints = [
        {
            "type": "ineq",
            "fun": lambda y: -problem.values(y)[1],
            "jac": lambda y: -problem.constraint_rows(y, everything),
        }
    ]
    if problem._equalities is not None:
        constraints.append(
            {
                "type": "eq",
                "fun": lambda y: problem.values(y)[2],
                "jac": problem._equality_jacobian,
            }
        )
    result = minimize(
        lambda y: problem.values(y)[0],
        problem.x0,
        jac=problem.objective_gradient,
        bounds=list(zip(problem.lower, problem.upper, strict=True)),
        constraints=constraints,
        method="SLSQP",
        options={"maxiter": 500, "ftol": 1e-14},
    )
    return float(result.fun)


def main() -> None:
    """Print the results."""
    print("Trusses (weight in lb)")
    for make in (ten_bar, twenty_five_bar, seventy_two_bar):
        truss = make()
        for method in ("mma", "gcmma"):
            start = time.perf_counter()
            result = Optimizer(
                truss.problem(0.5), Settings(method=method, max_iter=200)
            ).run()
            areas = truss.areas(result.x)
            print(
                f"  {make.__name__:15s} {method:6s} {truss.weight(areas):9.3f} "
                f"(published {truss.known[0]}) worst constraint "
                f"{truss.worst(areas):+.1e} {result.iterations} it "
                f"{result.status} {time.perf_counter() - start:.2f} s"
            )
    print("Hock-Schittkowski")
    for make in (hs71, hs100, hs113):
        problem, _, f_star = make()
        print(
            f"  {make.__name__}: published {f_star}, SLSQP {reference(make()[0]):.7f}"
        )
        for method in ("mma", "gcmma"):
            problem, _, f_star = make()
            settings = Settings(
                method=method, max_iter=300, ineq_tolerance=1e-6, eq_tolerance=1e-6
            )
            result = Optimizer(problem, settings).run()
            f, g, h = problem.values(result.x)
            print(
                f"    {method:6s} error {abs(f - f_star) / abs(f_star):.1e} "
                f"max g {g.max():+.1e} max|h| {np.abs(h).max(initial=0.0):.1e} "
                f"{result.iterations} it {result.status}"
            )
    print("Svanberg beam (closed-form optimum)")
    for n in (5, 100, 1000, 10_000):
        for method in ("mma", "gcmma"):
            problem, y_star, f_star = beam(n)
            start = time.perf_counter()
            result = Optimizer(
                problem, Settings(method=method, max_iter=300, ineq_tolerance=1e-6)
            ).run()
            f, g, _ = problem.values(result.x)[:3]
            print(
                f"  n={n:6d} {method:6s} error {abs(f - f_star) / f_star:.1e} "
                f"max x error {np.abs(result.x / y_star - 1).max():.1e} "
                f"{result.iterations} it {result.status} "
                f"{time.perf_counter() - start:.1f} s"
            )


if __name__ == "__main__":
    main()
