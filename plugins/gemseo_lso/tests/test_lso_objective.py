"""The gradient of the objective chained through vector-Jacobian products (plan 82).

The chain ``x → Loads → Work``: an objective ``work = Σ x + c Σ y²`` read from
the loads ``y = y0 + A x + 0.1 (A x)²`` of plan 76's chain, and the stresses
``g = (B y) / x - 1`` as constraints. ``Loads`` gives its vector-Jacobian
products and counts its whole Jacobians; ``PlainLoads`` is the same discipline
without them, whose objective gradient is GEMSEO's: the reference.
"""

import logging

import numpy as np
import pytest
from gemseo import create_design_space
from gemseo import create_scenario
from lso_disciplines import Loads
from lso_disciplines import Mass
from lso_disciplines import PlainLoads
from lso_disciplines import Stresses
from lso_disciplines import Work
from lso_disciplines import coupling
from lso_disciplines import local_reading

from gemseo_lso.gemseo.adapter import GemseoProblem
from gemseo_lso.gemseo.settings import LSO_GCMMA_Settings

logging.getLogger("gemseo").setLevel(logging.WARNING)
logging.getLogger("gemseo_lso").setLevel(logging.WARNING)

N = 30
LOWER, UPPER = 0.1, 2.0


def scenario(kind, objective="work", maximize=False):
    """``x → loads → (work, stress)``, minimizing (or maximizing) the objective."""
    loads = kind(coupling(2 * N, N, seed=3))
    stresses = Stresses({"loads": local_reading(N, 2 * N)})
    work = Work(N, 2 * N)
    space = create_design_space()
    space.add_variable("x", size=N, lower_bound=LOWER, upper_bound=UPPER, value=1.0)
    disciplines = (
        [loads, stresses, work] if objective == "work" else [loads, stresses, Mass(N)]
    )
    study = create_scenario(
        disciplines,
        objective,
        space,
        formulation_name="DisciplinaryOpt",
        maximize_objective=maximize,
    )
    study.add_constraint("stress", "ineq")
    return study, loads, work


def adapter(kind, objective="work", maximize=False, **settings):
    study, loads, work = scenario(kind, objective, maximize)
    problem = study.formulation.optimization_problem
    normalize = settings.get("normalize_design_space", True)
    problem.preprocess_functions(is_function_input_normalized=normalize)
    return GemseoProblem(problem, LSO_GCMMA_Settings(**settings)), loads, work


def analytic(loads, work, x):
    """d work / dx at the physical point ``x``."""
    linear = loads.matrix @ x
    y = loads.external + linear + 0.1 * linear**2
    return 1.0 + 2 * work.factor * (loads.derivative(x).T @ y)


@pytest.mark.parametrize("normalize", [True, False])
@pytest.mark.parametrize("maximize", [False, True])
def test_the_chained_gradient_equals_that_of_gemseo(normalize, maximize):
    problem, loads, work = adapter(
        Loads, maximize=maximize, normalize_design_space=normalize
    )
    reference, plain, _ = adapter(
        PlainLoads, maximize=maximize, normalize_design_space=normalize
    )
    assert problem.objective_source is not None and reference.objective_source is None
    unit = np.random.default_rng(0).uniform(0.2, 0.9, N)
    x = unit if normalize else LOWER + unit * (UPPER - LOWER)
    problem.values(x)
    reference.values(x)
    given = problem.objective_gradient(x)
    expected = reference.objective_gradient(x)
    physical = LOWER + unit * (UPPER - LOWER)
    exact = analytic(loads, work, physical) * ((UPPER - LOWER) if normalize else 1.0)
    np.testing.assert_allclose(given, expected, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(
        given, -exact if maximize else exact, rtol=1e-12, atol=1e-12
    )
    # One product call, the Jacobian of the loads never formed; the objective's
    # own discipline linearized once.
    assert (loads.products, loads.product_rows, loads.jacobians) == (1, [1], 0)
    assert work.jacobians == 1 and plain.jacobians == 1


def test_a_whole_run_never_forms_the_jacobian_of_the_loads():
    study, loads, _ = scenario(Loads)
    study.execute(algo_name="LSO_GCMMA", max_iter=200)
    reference, plain, _ = scenario(PlainLoads)
    reference.execute(algo_name="LSO_GCMMA", max_iter=200)
    result, expected = study.optimization_result, reference.optimization_result
    assert result.is_feasible
    assert result.f_opt == pytest.approx(expected.f_opt, rel=1e-6)
    np.testing.assert_allclose(result.x_opt, expected.x_opt, atol=1e-5)
    # The objective read from the loads, and still the loads never linearized.
    assert loads.jacobians == 0 and loads.products > 0
    assert plain.jacobians > 0


def test_an_objective_without_the_loads_keeps_the_gradient_of_gemseo():
    problem, loads, _ = adapter(Loads, objective="mass")
    assert problem.objective_source is None
    x = np.full(N, 0.5)
    problem.values(x)
    np.testing.assert_allclose(problem.objective_gradient(x), np.full(N, UPPER - LOWER))
    assert loads.products == 0
