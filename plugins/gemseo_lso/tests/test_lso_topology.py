import numpy as np
import pytest
from scipy import sparse

from gemseo_lso import Optimizer
from gemseo_lso import Settings
from gemseo_lso.benchmarks.topology.cases import cantilever
from gemseo_lso.benchmarks.topology.cases import l_bracket
from gemseo_lso.benchmarks.topology.disciplines import StressDiscipline
from gemseo_lso.benchmarks.topology.model import StressTopology
from gemseo_lso.benchmarks.topology.model import element_stiffness


def bar():
    """A 4 × 2 bar pulled by a unit traction on its right side (patch test)."""
    columns, rows = 4, 2

    def node(column, row):
        return row * (columns + 1) + column

    fixed = [2 * node(0, row) for row in range(rows + 1)] + [2 * node(0, 0) + 1]
    # Consistent nodal forces of a unit traction over a height of 2.
    loads = {
        2 * node(columns, 0): 0.5,
        2 * node(columns, 1): 1.0,
        2 * node(columns, 2): 0.5,
    }
    return StressTopology(
        mask=np.ones((rows, columns), dtype=bool),
        fixed=np.asarray(fixed),
        loads=loads,
        stress_limit=2.0,
    )


def test_the_element_stiffness():
    matrix = element_stiffness()
    assert matrix == pytest.approx(matrix.T)
    eigenvalues = np.linalg.eigvalsh(matrix)
    assert np.sum(np.abs(eigenvalues) < 1e-12) == 3  # Two translations, a rotation.


def test_a_uniform_traction_gives_the_exact_solution():
    problem = bar()
    state = problem.state(problem.x0)
    # u_x = sigma x / E at the right side: x = 4, sigma = 1, E = 1 (E_min aside).
    right = [np.flatnonzero(problem.grid_nodes == row * 5 + 4)[0] for row in range(3)]
    assert state.displacements[[2 * node for node in right]] == pytest.approx(
        4.0, rel=1e-6
    )
    # Full density: the relaxed stress is von Mises, here the traction.
    assert problem.stresses(problem.x0) == pytest.approx(1.0, rel=1e-6)
    _, constraints, _ = problem.values(problem.x0)
    assert constraints == pytest.approx(1.0 / 2.0 - 1.0, rel=1e-6)


@pytest.fixture
def beam():
    problem = cantilever(6, 3)
    x = np.random.default_rng(0).uniform(0.3, 1.0, problem.elements)
    return problem, x


def test_the_rows_by_adjoint_are_the_finite_differences(beam):
    problem, x = beam
    rows = np.array([0, 4, 11, 17])
    analytic = problem.constraint_rows(x, rows)
    base = problem.values(x)[1][rows]
    step = 1e-7
    differences = np.empty_like(analytic)
    for j in range(problem.elements):
        moved = x.copy()
        moved[j] += step
        differences[:, j] = (problem.values(moved)[1][rows] - base) / step
    assert analytic == pytest.approx(differences, abs=1e-4 * np.abs(differences).max())
    assert problem.rows == 4


def test_the_directions_by_the_direct_mode_are_the_rows(beam):
    problem, x = beam
    directions = sparse.csc_matrix(
        np.random.default_rng(1).standard_normal((problem.elements, 3))
    )
    products = problem.directional_derivatives(x, directions)
    rows = problem.constraint_rows(x, np.arange(problem.elements))
    assert products == pytest.approx(rows @ directions.toarray(), abs=1e-10)
    assert problem.products == 3


def test_the_aggregated_stress_and_its_gradient(beam):
    problem, x = beam
    norm, gradient = problem.aggregated(x, 8.0)
    ratios = problem.stresses(x) / problem.stress_limit
    assert norm == pytest.approx(np.sum(ratios**8) ** (1 / 8) - 1)
    step = 1e-7
    for j in (0, 7, 15):
        moved = x.copy()
        moved[j] += step
        difference = (problem.aggregated(moved, 8.0)[0] - norm) / step
        assert gradient[j] == pytest.approx(difference, rel=1e-4, abs=1e-6)


def test_the_pattern_of_the_stresses():
    problem = cantilever(20, 10)
    pattern = problem.sparsity()
    assert pattern.shape == (200, 200)
    assert pattern.diagonal().all()
    reach = problem.radius + problem.filter_radius
    assert pattern.sum(axis=1).max() <= np.pi * (reach + 1) ** 2


def test_a_small_bracket_is_optimized():
    problem = l_bracket(10, stress_limit=45)
    settings = Settings(method="mma", move_limit=0.2, max_iter=40)
    result = Optimizer(problem, settings).run()
    stresses = problem.stresses(result.x)
    assert stresses.max() <= problem.stress_limit * (1 + 1e-3)
    assert result.objective < 0.8


def test_the_discipline_gives_rows_and_directions(beam):
    problem, x = beam
    discipline = StressDiscipline(problem)
    rows = np.array([1, 2])
    given = discipline.compute_jacobian_rows("stress", rows, {"x": x})["x"]
    assert given == pytest.approx(problem.constraint_rows(x, rows))
    directions = {"x": np.eye(problem.elements)[:, :2]}
    products = discipline.compute_directional_derivatives(
        "stress", directions, {"x": x}
    )
    full = problem.constraint_rows(x, np.arange(problem.elements))
    assert products == pytest.approx(full[:, :2], abs=1e-10)
    output = discipline.execute({"x": x})
    assert output["volume"][0] == pytest.approx(problem.values(x)[0])


def test_the_best_feasible_point_is_returned():
    # Without restoration, the last iterate leaves the constraints: the result
    # is the best feasible point met, an early one here.
    problem = l_bracket(20)
    settings = Settings(
        method="mma", move_limit=0.2, max_iter=22, restoration_iterations=0
    )
    optimizer = Optimizer(problem, settings)
    reports = list(optimizer)
    assert reports[-1].max_constraint > settings.ineq_tolerance
    result = optimizer.result
    assert result.max_constraint <= settings.ineq_tolerance
    assert "best feasible point" in result.message
    assert problem.stresses(result.x).max() <= problem.stress_limit * (1 + 1e-5)


def test_feasibility_is_restored_before_the_end():
    problem = l_bracket(18)
    settings = Settings(
        method="mma", move_limit=0.2, max_iter=25, restoration_iterations=10
    )
    optimizer = Optimizer(problem, settings)
    reports = list(optimizer)
    assert any(report.restoration for report in reports)
    assert reports[-1].max_constraint <= settings.ineq_tolerance
    assert optimizer.result.objective < 0.5  # Without: an early design, 0.52.


def test_the_kkt_residual_of_a_volume_under_stresses():
    # A volume fraction has a gradient of 1/n per variable, the stresses of
    # order 1: measured against the gradient of the objective alone, the
    # residual stayed at 0.5 to 0.6 here (10 to 10^6 through GEMSEO).
    problem = l_bracket(10)
    settings = Settings(method="mma", move_limit=0.2, max_iter=40)
    reports = list(Optimizer(problem, settings))
    assert reports[-1].kkt_residual < 0.2


def test_the_bracket_describes_its_physics():
    problem = l_bracket(10)
    description = problem.physical_description()
    assert (description["grid"]["rows"], description["grid"]["columns"]) == (10, 10)
    cells = description["variable_cells"]
    assert len(cells) == problem.elements == 64
    assert description["constraint_cells"] == {"stress": cells}
    # The inner corner of the L is at node (4, 4): the elements around it.
    (corner,) = description["features"]
    assert corner["name"] == "reentrant corner"
    assert corner["cells"] == [33, 34, 43]
    # Clamped along the top of the vertical arm, loaded at the tip of the other.
    (support,) = description["supports"]
    assert support["cells"] == [90, 91, 92, 93]
    assert support["blocks"] == "x and y"
    (load,) = description["loads"]
    assert load["cells"] == [19, 29, 39]
    assert load["direction"] == [0.0, -1.0]
    assert load["magnitude"] == pytest.approx(10.0)
    assert description["minimum_member_size"] == pytest.approx(3.0)
    names = [item["name"] for item in description["fields"]]
    assert names == [
        "density",
        "stress_ratio",
        "strain_energy",
        "principal_sign",
        "displacement",
    ]


def test_the_physical_fields_of_the_bracket():
    problem = l_bracket(10)
    x = np.linspace(0.2, 1.0, problem.elements)
    fields = problem.physical_fields(x)
    assert all(values.shape == (problem.elements,) for values in fields.values())
    assert fields["density"] == pytest.approx(problem.filter @ x)
    assert fields["stress_ratio"] == pytest.approx(
        problem.stresses(x) / problem.stress_limit
    )
    assert (fields["strain_energy"] > 0).all()
    assert set(np.unique(fields["principal_sign"])) <= {-1.0, 0.0, 1.0}
    discipline = StressDiscipline(problem)
    assert discipline.physical_fields({"x": x})["density"] == pytest.approx(
        fields["density"]
    )


def test_the_end_of_a_budget_of_evaluations_is_restored():
    # GEMSEO stops on evaluations: GCMMA makes several per iteration, and the
    # run ends long before max_iter iterations. The restoration starts when
    # the evaluations left would last no more than it.
    problem = l_bracket(18)
    settings = Settings(
        method="gcmma",
        move_limit=0.2,
        max_iter=600,
        max_evaluations=60,
        restoration_iterations=6,
    )
    optimizer = Optimizer(problem, settings)
    reports = []
    while optimizer.state.evaluations < 60 and not optimizer.finished:
        reports.append(optimizer.step())
    assert reports[-1].iteration < 600 - 6  # Not near max_iter.
    assert any(report.restoration for report in reports)
    assert reports[-1].max_constraint <= settings.ineq_tolerance
    # Without the budget, the run ended above the limit, its best feasible
    # point an early one (0.62).
    assert optimizer.result.objective < 0.5
