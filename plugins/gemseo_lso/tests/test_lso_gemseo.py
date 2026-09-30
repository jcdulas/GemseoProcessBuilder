import logging

import numpy as np
import pytest
from gemseo import create_design_space
from gemseo import create_discipline
from gemseo import create_scenario
from gemseo.algos.opt.factory import OptimizationLibraryFactory
from gemseo.problems.mdo.sellar.sellar_1 import Sellar1
from gemseo.problems.mdo.sellar.sellar_2 import Sellar2
from gemseo.problems.mdo.sellar.sellar_design_space import SellarDesignSpace
from gemseo.problems.mdo.sellar.sellar_system import SellarSystem
from lso_disciplines import CoupledLocal
from lso_disciplines import Feedback
from lso_disciplines import Halved
from lso_disciplines import Local
from lso_disciplines import RowsLocal
from lso_disciplines import RowsTangentLocal
from pydantic import ValidationError
from scipy import sparse

from gemseo_lso import ProblemError
from gemseo_lso.benchmarks.synthetic import LocalConstraints
from gemseo_lso.core.coloring import color
from gemseo_lso.gemseo import LargeScaleOptimization
from gemseo_lso.gemseo.settings import LSO_GCMMA_Settings
from gemseo_lso.gemseo.settings import LSO_MMA_Settings
from gemseo_lso.gemseo.settings import core_settings
from gemseo_lso.gemseo.sources import top_disciplines

logging.getLogger("gemseo").setLevel(logging.WARNING)
logging.getLogger("gemseo_lso").setLevel(logging.WARNING)

SIZE = 100


def sellar(algorithm):
    scenario = create_scenario(
        [Sellar1(), Sellar2(), SellarSystem()],
        "obj",
        SellarDesignSpace(),
        formulation_name="MDF",
    )
    scenario.add_constraint("c_1", "ineq")
    scenario.add_constraint("c_2", "ineq")
    scenario.execute(algo_name=algorithm, max_iter=100)
    return scenario.optimization_result


def rosenbrock(algorithm):
    discipline = create_discipline(
        "AnalyticDiscipline",
        expressions={"f": "(1 - x)**2 + 100*(y - x**2)**2", "g": "x**2 + y**2 - 1"},
    )
    space = create_design_space()
    space.add_variable("x", lower_bound=-1.5, upper_bound=1.5, value=0.0)
    space.add_variable("y", lower_bound=-1.5, upper_bound=1.5, value=0.0)
    scenario = create_scenario(
        [discipline], "f", space, formulation_name="DisciplinaryOpt"
    )
    scenario.add_constraint("g", "ineq")
    scenario.execute(algo_name=algorithm, max_iter=300)
    return scenario.optimization_result


ROSENBROCK = (0.0456748, [0.786415, 0.617698])
"""The Rosenbrock function in the unit disk: SLSQP's and NLOPT_MMA's optimum
(computed once: SLSQP alone takes more than a second)."""


@pytest.mark.parametrize("algorithm", ["LSO_MMA", "LSO_GCMMA"])
def test_sellar_as_slsqp(algorithm):
    result = sellar(algorithm)
    reference = sellar("SLSQP")
    assert result.f_opt == pytest.approx(reference.f_opt, rel=1e-4)
    assert result.x_opt == pytest.approx(reference.x_opt, abs=1e-3)
    assert result.is_feasible
    assert "KKT conditions met" in result.message
    assert result.status == 0


def test_the_constrained_rosenbrock():
    # LSO_MMA cycles there before switching to GCMMA: over a second.
    result = rosenbrock("LSO_GCMMA")
    assert result.f_opt == pytest.approx(ROSENBROCK[0], rel=1e-4)
    assert result.x_opt == pytest.approx(ROSENBROCK[1], abs=1e-3)
    assert result.is_feasible


def synthetic(discipline, upstream=(), **settings):
    """A scenario on the synthetic problem, run; the result and the problem."""
    problem = discipline.problem
    space = create_design_space()
    name = "u" if upstream else "x"
    scale = 2.0 if upstream else 1.0
    space.add_variable(
        name,
        size=SIZE,
        lower_bound=0.0,
        upper_bound=scale,
        value=problem.x0 * scale,
    )
    scenario = create_scenario(
        [*upstream, discipline], "f", space, formulation_name="DisciplinaryOpt"
    )
    output = settings.pop("output", "g")
    scenario.add_constraint(output, "ineq", positive=output == "minus_g")
    scenario.execute(algo_name="LSO_GCMMA", max_iter=500, **settings)
    result = scenario.optimization_result
    x = result.x_opt / scale
    return result, np.abs(x - problem.solution).max()


def local(kind=Local, **options):
    return kind(LocalConstraints(SIZE, active_share=0.05, seed=1), **options)


def test_full_jacobians_dense_or_sparse():
    sparse_result, sparse_error = synthetic(local())
    dense_result, dense_error = synthetic(local(dense=True))
    assert sparse_error < 5e-3
    assert dense_error < 5e-3
    assert sparse_result.f_opt == pytest.approx(dense_result.f_opt, rel=1e-6)


def test_the_row_mode_asks_for_the_rows_of_the_working_set_only():
    full, _ = synthetic(local())
    discipline = local(RowsLocal)
    result, error = synthetic(discipline)
    assert error < 5e-3
    assert result.f_opt == pytest.approx(full.f_opt, rel=1e-6)
    assert discipline.full_jacobians == 0
    rows = discipline.problem.rows
    assert 0 < rows < 0.3 * SIZE * discipline.problem.evaluations
    assert f"{rows} constraint gradients" in result.message


@pytest.mark.parametrize("kind", [Local, RowsLocal])
def test_normalization_and_signs(kind):
    # u in [0, 2], x = u / 2 upstream; the constraints written -g >= 0.
    discipline = local(kind)
    discipline.problem.rows = 0
    result, error = synthetic(discipline, upstream=[Halved(SIZE)], output="minus_g")
    assert error < 5e-3
    assert result.is_feasible
    if kind is RowsLocal:
        assert discipline.full_jacobians == 0
        assert discipline.problem.rows > 0


def test_a_coupled_discipline_is_refused_in_row_mode():
    discipline = CoupledLocal(LocalConstraints(SIZE, active_share=0.05, seed=1))
    space = create_design_space()
    space.add_variable("x", size=SIZE, lower_bound=0.0, upper_bound=1.0, value=0.5)
    scenario = create_scenario(
        [discipline, Feedback()], "f", space, formulation_name="MDF"
    )
    scenario.add_constraint("g", "ineq")
    with pytest.raises(ProblemError, match="coupled"):
        scenario.execute(algo_name="LSO_GCMMA", max_iter=10)


def test_the_disciplines_of_a_problem_are_found():
    # GEMSEO 6 exposes them through a private attribute of its adapters only.
    discipline = local()
    space = create_design_space()
    space.add_variable("x", size=SIZE, lower_bound=0.0, upper_bound=1.0, value=0.5)
    scenario = create_scenario(
        [discipline], "f", space, formulation_name="DisciplinaryOpt"
    )
    scenario.add_constraint("g", "ineq")
    problem = scenario.formulation.optimization_problem
    assert discipline in top_disciplines(problem)


def test_the_hybrid_mode_through_gemseo():
    calls = []

    def pattern(variables, constraints):
        calls.append((variables, constraints))
        return discipline.problem.pattern

    rows_mode = local(RowsLocal)
    synthetic(rows_mode)
    discipline = local(RowsTangentLocal)
    result, error = synthetic(
        discipline, jacobian_mode="hybrid", sparsity_pattern=pattern
    )
    assert error < 5e-3
    assert calls == [([("x", SIZE)], [("g", SIZE)])]
    # The exact rows of the constraints close to activity only.
    assert 0 < discipline.problem.rows < rows_mode.problem.rows
    assert discipline.full_jacobians == 0
    colors = color(discipline.problem.pattern, 1, 2).total
    assert discipline.problem.products % colors == 0
    assert f"{discipline.problem.products} directional derivatives" in result.message


def test_the_hybrid_mode_by_finite_differences():
    discipline = local()
    result, error = synthetic(
        discipline,
        jacobian_mode="hybrid",
        sparsity_pattern=lambda variables, constraints: discipline.problem.pattern,
    )
    assert error < 5e-3
    assert result.is_feasible


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        (np.ones((SIZE, SIZE), dtype=bool), r"scipy\.sparse"),
        (sparse.eye(3, dtype=bool, format="csr"), "shape"),
        (None, "sparsity pattern"),
    ],
)
def test_a_wrong_pattern_is_refused(pattern, message):
    with pytest.raises(ProblemError, match=message):
        synthetic(
            local(),
            jacobian_mode="hybrid",
            sparsity_pattern=None if pattern is None else lambda v, c: pattern,
        )


def test_the_settings():
    with pytest.raises(ValidationError, match="store_jacobian"):
        LSO_GCMMA_Settings(store_jacobian=True)
    with pytest.raises(ValidationError, match="screening_margin_min"):
        LSO_GCMMA_Settings(screening_margin=0.1, screening_margin_min=0.2)
    assert LSO_GCMMA_Settings().jacobian_mode == "rows"


def test_gemseo_lists_the_algorithms():
    factory = OptimizationLibraryFactory()
    for name in ("LSO_MMA", "LSO_GCMMA"):
        assert name in factory.algorithms
        info = LargeScaleOptimization.ALGORITHM_INFOS[name]
        assert info.require_gradient
        assert info.handle_equality_constraints
        assert info.handle_inequality_constraints


def test_gemseo_tolerances_apply_to_outer_iterations():
    # GEMSEO's ftol compares its last evaluations: GCMMA's inner iterations
    # evaluate close points, taken for a stagnation (a bracket stopped after 13
    # of its 160 iterations). The optimizer applies it to its iterations.
    result, error = synthetic(local(RowsLocal), ftol_rel=1e-3)
    assert "GEMSEO stopped the driver" not in result.message
    assert "objective changed less than" in result.message
    assert result.is_feasible
    assert error < 5e-2


def test_gemseo_gives_its_budget_of_evaluations_to_the_core():
    settings = LSO_MMA_Settings(max_iter=123)
    core = core_settings(settings, "mma")
    assert (core.max_iter, core.max_evaluations) == (123, 123)
