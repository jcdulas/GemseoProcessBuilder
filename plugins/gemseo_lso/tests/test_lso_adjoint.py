"""Rows chained through intermediate disciplines by vector-Jacobian products (plan 76).

The chain ``x → Loads → Stresses``: the loads ``y = y0 + A x + 0.1 (A x)²`` of
a structure, ``A`` sparse, and a stress per item ``g = (B y) / x - 1``, ``B``
local. ``Loads`` gives its vector-Jacobian products (``AdjointJacobian``) and
counts its whole Jacobians; ``PlainLoads`` is the same discipline without the
protocol: the path of a full Jacobian, the reference.
"""

import logging

import numpy as np
import pytest
from gemseo import create_design_space
from gemseo import create_scenario
from lso_disciplines import AdjointStresses
from lso_disciplines import Loads
from lso_disciplines import Mass
from lso_disciplines import PlainLoads
from lso_disciplines import Stresses
from lso_disciplines import coupling
from lso_disciplines import local_reading
from scipy import sparse

from gemseo_lso.benchmarks.topology.cases import cantilever
from gemseo_lso.benchmarks.topology.split import split_disciplines
from gemseo_lso.gemseo import AdjointJacobian
from gemseo_lso.gemseo.adapter import GemseoProblem
from gemseo_lso.gemseo.settings import LSO_GCMMA_Settings

logging.getLogger("gemseo").setLevel(logging.WARNING)
logging.getLogger("gemseo_lso").setLevel(logging.WARNING)

N = 30
"""Items: design variables and constraints of each stress."""

LOWER, UPPER = 0.1, 2.0


def scenario(disciplines, constraints=("stress",), positive=False):
    """A scenario minimizing the mass under the constraints."""
    space = create_design_space()
    space.add_variable("x", size=N, lower_bound=LOWER, upper_bound=UPPER, value=1.0)
    study = create_scenario(
        [Mass(N), *disciplines], "mass", space, formulation_name="DisciplinaryOpt"
    )
    for name in constraints:
        study.add_constraint(name, "ineq", positive=positive)
    return study


def adapter(disciplines, constraints=("stress",), positive=False, **settings):
    """The problem of the optimizer on a scenario, at its start."""
    study = scenario(disciplines, constraints, positive)
    problem = study.formulation.optimization_problem
    problem.preprocess_functions()
    return GemseoProblem(problem, LSO_GCMMA_Settings(**settings))


def chain(kind=Loads, stresses=Stresses):
    """``x → loads → stress``."""
    loads = kind(coupling(2 * N, N, seed=3))
    return loads, stresses({"loads": local_reading(N, 2 * N)})


def analytic(loads, stresses, x):
    """The Jacobian of the stresses with respect to x, dense."""
    y = loads.external + loads.matrix @ x + 0.1 * (loads.matrix @ x) ** 2
    reading = stresses.loads["loads"]
    force = reading @ y
    return (
        np.diag(-force / x**2)
        + np.diag(1 / x) @ (reading @ loads.derivative(x)).toarray()
    )


def point(problem, seed=0):
    """A point of the normalized space, evaluated (as the optimizer does)."""
    x = np.random.default_rng(seed).uniform(0.2, 0.9, N)
    problem.values(x)
    return x


def dense(rows):
    return rows.toarray() if sparse.issparse(rows) else np.asarray(rows)


def test_the_protocol_is_exported():
    loads, _ = chain()
    assert isinstance(loads, AdjointJacobian)
    assert not isinstance(chain(PlainLoads)[0], AdjointJacobian)


def test_the_rows_equal_those_of_the_full_jacobian_path():
    loads, stresses = chain()
    problem = adapter([loads, stresses])
    plain, plain_stresses = chain(PlainLoads)
    reference = adapter([plain, plain_stresses])
    x = point(problem)
    point(reference)
    rows = np.array([0, 3, 4, 17, 29])
    given = dense(problem.constraint_rows(x, rows))
    expected = dense(reference.constraint_rows(x, rows))
    physical = LOWER + x * (UPPER - LOWER)
    exact = analytic(loads, stresses, physical)[rows] * (UPPER - LOWER)
    np.testing.assert_allclose(given, expected, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(given, exact, rtol=1e-12, atol=1e-12)
    # One product call for the batch, the Jacobian of the loads never formed.
    assert (loads.products, loads.product_rows, loads.jacobians) == (1, [5], 0)
    assert plain.jacobians == 1


def test_a_whole_run_never_forms_the_jacobian_of_the_loads():
    loads, stresses = chain()
    study = scenario([loads, stresses])
    calls = []
    original = GemseoProblem.constraint_rows

    def counted(self, x, rows):
        calls.append(len(rows))
        return original(self, x, rows)

    GemseoProblem.constraint_rows = counted  # type: ignore[method-assign]
    try:
        study.execute(algo_name="LSO_GCMMA", max_iter=200)
    finally:
        GemseoProblem.constraint_rows = original  # type: ignore[method-assign]
    plain, plain_stresses = chain(PlainLoads)
    reference = scenario([plain, plain_stresses])
    reference.execute(algo_name="LSO_GCMMA", max_iter=200)
    result, expected = study.optimization_result, reference.optimization_result
    assert result.is_feasible
    assert result.f_opt == pytest.approx(expected.f_opt, rel=1e-6)
    np.testing.assert_allclose(result.x_opt, expected.x_opt, atol=1e-5)
    # The gradient of the objective included: the loads are never linearized.
    assert loads.jacobians == 0
    assert plain.jacobians > 0
    # One product call per point and batch of rows.
    assert loads.products == len(calls) > 0
    assert loads.product_rows == calls


def test_two_constraints_fed_by_the_same_loads_make_one_call():
    loads, stress = chain()
    reading = local_reading(N, 2 * N)
    buckling = Stresses({"loads": reading[::-1]}, "buckling", "Buckling")
    problem = adapter([loads, stress, buckling], ("stress", "buckling"))
    plain, plain_stress = chain(PlainLoads)
    plain_buckling = Stresses({"loads": reading[::-1]}, "buckling", "Buckling")
    reference = adapter([plain, plain_stress, plain_buckling], ("stress", "buckling"))
    x = point(problem)
    point(reference)
    rows = np.array([1, 2, N + 2, N + 7, 5])  # Both constraints, in any order.
    np.testing.assert_allclose(
        dense(problem.constraint_rows(x, rows)),
        dense(reference.constraint_rows(x, rows)),
        rtol=1e-12,
        atol=1e-12,
    )
    # Stacked: the weights of the two constraints in one call.
    assert (loads.products, loads.product_rows) == (1, [5])
    # Linearized once for both, by GEMSEO's cache of the discipline.
    assert plain.jacobians == 1


def series(first_kind, second_kind):
    """``x → loads → forces → stress``: two intermediates in series."""
    first = first_kind(coupling(2 * N, N, seed=3), name="First")
    second = second_kind(
        coupling(2 * N, 2 * N, seed=4), "loads", "forces", name="Second"
    )
    stresses = Stresses({"forces": local_reading(N, 2 * N)})
    return first, second, stresses


@pytest.mark.parametrize(
    ("first_kind", "second_kind"),
    [(Loads, Loads), (PlainLoads, Loads), (Loads, PlainLoads)],
)
def test_two_intermediates_in_series(first_kind, second_kind):
    first, second, stresses = series(first_kind, second_kind)
    problem = adapter([first, second, stresses])
    reference = adapter(list(series(PlainLoads, PlainLoads)))
    x = point(problem)
    point(reference)
    rows = np.arange(0, N, 3)
    np.testing.assert_allclose(
        dense(problem.constraint_rows(x, rows)),
        dense(reference.constraint_rows(x, rows)),
        rtol=1e-12,
        atol=1e-12,
    )
    problem.constraint_rows(x, np.array([1, 2]))  # Again at the same point.
    for discipline in (first, second):
        if isinstance(discipline, Loads):
            assert (discipline.products, discipline.jacobians) == (2, 0)
        else:
            assert discipline.jacobians == 1  # Once per point.


def test_loads_with_the_protocol_beside_loads_without():
    with_products = Loads(coupling(2 * N, N, seed=3), output_name="loads")
    without = PlainLoads(coupling(2 * N, N, seed=5), output_name="other_loads")
    reading = local_reading(N, 2 * N)
    stresses = Stresses({"loads": reading, "other_loads": reading})
    problem = adapter([with_products, without, stresses])
    x = point(problem)
    rows = np.array([0, 9, 21])
    physical = LOWER + x * (UPPER - LOWER)
    y = {
        loads.output_name: loads.external
        + loads.matrix @ physical
        + 0.1 * (loads.matrix @ physical) ** 2
        for loads in (with_products, without)
    }
    force = reading @ (y["loads"] + y["other_loads"])
    derivative = with_products.derivative(physical) + without.derivative(physical)
    exact = (
        np.diag(-force / physical**2)
        + np.diag(1 / physical) @ (reading @ derivative).toarray()
    )
    np.testing.assert_allclose(
        dense(problem.constraint_rows(x, rows)),
        exact[rows] * (UPPER - LOWER),
        rtol=1e-12,
        atol=1e-12,
    )
    assert (with_products.products, with_products.jacobians) == (1, 0)
    assert without.jacobians == 1


@pytest.mark.parametrize("normalize", [True, False])
def test_normalization_and_signs(normalize):
    # The constraints written -stress >= 0: GEMSEO negates them, and their rows.
    loads, stresses = chain()
    problem = adapter(
        [loads, stresses], positive=True, normalize_design_space=normalize
    )
    x = point(problem) if normalize else LOWER + point(problem) * (UPPER - LOWER)
    problem.values(x)
    rows = np.array([2, 8])
    physical = LOWER + x * (UPPER - LOWER) if normalize else x
    scale = (UPPER - LOWER) if normalize else 1.0
    np.testing.assert_allclose(
        dense(problem.constraint_rows(x, rows)),
        -analytic(loads, stresses, physical)[rows] * scale,
        rtol=1e-12,
        atol=1e-12,
    )


def test_the_products_by_batches_of_rows():
    loads, stresses = chain()
    problem = adapter([loads, stresses], row_batch_size=4)
    plain, plain_stresses = chain(PlainLoads)
    reference = adapter([plain, plain_stresses])
    x = point(problem)
    point(reference)
    rows = np.arange(10)
    np.testing.assert_allclose(
        dense(problem.constraint_rows(x, rows)),
        dense(reference.constraint_rows(x, rows)),
        rtol=1e-12,
        atol=1e-12,
    )
    assert loads.product_rows == [4, 4, 2]


def test_a_constraint_giving_products_instead_of_rows():
    loads, stresses = chain(stresses=AdjointStresses)
    problem = adapter([loads, stresses])
    x = point(problem)
    rows = np.array([4, 0, 13])
    physical = LOWER + x * (UPPER - LOWER)
    np.testing.assert_allclose(
        dense(problem.constraint_rows(x, rows)),
        analytic(loads, stresses.stresses, physical)[rows] * (UPPER - LOWER),
        rtol=1e-12,
        atol=1e-12,
    )
    assert loads.jacobians == 0


def test_directional_derivatives_through_the_loads():
    loads, stresses = chain()
    problem = adapter([loads, stresses])
    x = point(problem)
    rng = np.random.default_rng(2)
    directions = sparse.csc_matrix(rng.standard_normal((N, 3)))
    products = problem.directional_derivatives(x, directions)
    step = 1e-6
    for column in range(3):
        d = directions[:, column].toarray().ravel()
        _, forward, _ = problem.values(x + step * d)
        _, backward, _ = problem.values(x - step * d)
        np.testing.assert_allclose(
            products[:, column], (forward - backward) / (2 * step), rtol=1e-6
        )
    assert (loads.tangents, loads.jacobians) == (3, 0)


@pytest.mark.parametrize("products", [True, False])
def test_the_split_topology_problem_gives_the_rows_of_the_whole_one(products):
    problem = cantilever(12, 6)
    displacements, stresses, volume = split_disciplines(problem, products)
    space = create_design_space()
    size = problem.elements
    space.add_variable("x", size=size, lower_bound=0.0, upper_bound=1.0, value=0.7)
    study = create_scenario(
        [volume, displacements, stresses],
        "volume",
        space,
        formulation_name="DisciplinaryOpt",
    )
    study.add_constraint("stress", "ineq")
    optimization = study.formulation.optimization_problem
    optimization.preprocess_functions()
    adapted = GemseoProblem(optimization, LSO_GCMMA_Settings())
    x = np.random.default_rng(4).uniform(0.3, 1.0, size)
    _, values, _ = adapted.values(x)
    whole = cantilever(12, 6)
    _, expected, _ = whole.values(x)
    np.testing.assert_allclose(values, expected, rtol=1e-12)
    rows = np.array([0, 7, 31, 70])
    np.testing.assert_allclose(
        dense(adapted.constraint_rows(x, rows)),
        whole.constraint_rows(x, rows),
        rtol=1e-9,
        atol=1e-12,
    )
    if products:
        assert (displacements.jacobians, displacements.product_rows) == (0, 4)
    else:
        assert displacements.jacobians == 1
