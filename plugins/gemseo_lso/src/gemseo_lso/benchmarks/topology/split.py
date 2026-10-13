"""The topology problem split into displacements and stresses (plan 76, spec § 9).

The structure of a sizing whose reserve factors are computed from internal loads
computed by another discipline: the stresses read the displacements, computed
by a finite-element solve.

- ``DisplacementsDiscipline``: ``u``, the displacements of the free degrees of
  freedom, ``K(x̃) u = f`` with ``x̃ = H x``. GEMSEO's Jacobian
  ``du/dx = -K⁻¹ S H`` costs one solve per element and is dense (degrees of
  freedom × elements): the path of a full Jacobian.
- ``AdjointDisplacementsDiscipline``: the same, giving the vector-Jacobian
  products ``W du/dx = -(K⁻¹ Wᵀ)ᵀ S H`` (``AdjointJacobian``): one solve per row
  of weights, on the factorization of the point.
- ``StressesDiscipline``: the stress constraints of the elements from the
  densities and the displacements, giving their rows (``RowJacobian``):
  ``∂g/∂u``, sparse (each element reads its 8 degrees of freedom), and
  ``∂g/∂x``, through the relaxation and the filter.
- ``VolumeDiscipline``: the volume fraction, the objective.

The rows chained through the displacements are those of
``StressTopology.constraint_rows``.

GEMSEO imports these modules only when the benchmarks are run.
"""

from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any

import numpy as np
from gemseo.core.discipline import Discipline
from scipy import sparse

from gemseo_lso.benchmarks.topology.model import StressTopology
from gemseo_lso.benchmarks.topology.model import solve


class DisplacementsDiscipline(Discipline):  # type: ignore[misc]
    """``displacements`` of the free degrees of freedom, from the densities ``x``.

    Args:
        problem: The topology problem.
    """

    def __init__(self, problem: StressTopology) -> None:
        super().__init__("Displacements")
        self.problem = problem
        self.jacobians = 0
        """Whole Jacobians computed."""
        self.products = 0
        """Calls of ``compute_vector_jacobian_products``."""
        self.product_rows = 0
        """Rows of weights received."""
        self.io.input_grammar.update_from_data({"x": problem.x0.copy()})
        self.io.output_grammar.update_from_data(
            {"displacements": np.zeros(problem.free.size)}
        )
        self.io.input_grammar.defaults = {"x": problem.x0.copy()}

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        state = self.problem.state(np.asarray(input_data["x"], dtype=float))
        return {"displacements": state.displacements[self.problem.free].copy()}

    def _compute_jacobian(
        self, input_names: Iterable[str] = (), output_names: Iterable[str] = ()
    ) -> None:
        """``du/dx = -K⁻¹ S H``: one solve per element, dense."""
        self.jacobians += 1
        problem = self.problem
        state = problem.state(np.asarray(self.io.data["x"], dtype=float))
        problem.solves += problem.elements
        motions = -solve(state.solver, state.residual.toarray())  # du/dx̃
        jacobian = np.asarray(sparse.csr_matrix(problem.filter.T) @ motions.T).T
        self.jac = {"displacements": {"x": jacobian}}


class AdjointDisplacementsDiscipline(DisplacementsDiscipline):
    """``DisplacementsDiscipline`` giving vector-Jacobian products.

    Args:
        problem: The topology problem.
    """

    def compute_vector_jacobian_products(
        self,
        weights: Mapping[str, Any],
        input_data: Mapping[str, Any],
        input_names: Sequence[str],
    ) -> dict[str, Any]:
        """``W du/dx = -(K⁻¹ Wᵀ)ᵀ S H``: one solve with ``k`` right-hand sides."""
        problem = self.problem
        block = weights["displacements"]
        self.products += 1
        self.product_rows += block.shape[0]
        problem.solves += block.shape[0]
        state = problem.state(np.asarray(input_data["x"], dtype=float))
        seeds = block.T.toarray() if sparse.issparse(block) else np.asarray(block).T
        adjoints = solve(state.solver, seeds)  # K is symmetric.
        filtered = -(state.residual.T @ adjoints)  # (elements, k): by x̃
        return {"x": np.asarray(sparse.csr_matrix(problem.filter.T) @ filtered).T}


class StressesDiscipline(Discipline):  # type: ignore[misc]
    """``stress``, ``sigma / sigma_lim - 1`` per element, from ``x`` and ``u``.

    Args:
        problem: The topology problem.
    """

    def __init__(self, problem: StressTopology) -> None:
        super().__init__("Stresses")
        self.problem = problem
        size = problem.elements
        self.io.input_grammar.update_from_data(
            {"x": problem.x0.copy(), "displacements": np.zeros(problem.free.size)}
        )
        self.io.output_grammar.update_from_data({"stress": np.zeros(size)})
        self.io.input_grammar.defaults = {
            "x": problem.x0.copy(),
            "displacements": np.zeros(problem.free.size),
        }

    def _terms(
        self, input_data: Mapping[str, Any]
    ) -> tuple[np.ndarray, np.ndarray, sparse.csc_matrix, np.ndarray]:
        """The densities, the stresses and their partial derivatives."""
        problem = self.problem
        filtered = problem.filter @ np.asarray(input_data["x"], dtype=float)
        displacements = np.zeros(problem.size)
        displacements[problem.free] = input_data["displacements"]
        von_mises, stress_rows, direct = problem.stress_terms(filtered, displacements)
        return filtered, von_mises, stress_rows, direct

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        filtered, von_mises, _, _ = self._terms(input_data)
        relaxed = np.maximum(filtered, 0.0) ** self.problem.relaxation
        return {"stress": relaxed * von_mises / self.problem.stress_limit - 1}

    def compute_jacobian_rows(
        self, output_name: str, rows: np.ndarray, input_data: Mapping[str, Any]
    ) -> dict[str, Any]:
        """``∂g/∂u`` (sparse) and ``∂g/∂x`` (through the filter) of some elements."""
        self.problem.rows += len(rows)
        _, _, stress_rows, direct = self._terms(input_data)
        by_density = sparse.diags(direct[rows]) @ self.problem.filter[rows]
        return {
            "displacements": sparse.csr_matrix(stress_rows[:, rows].T),
            "x": sparse.csr_matrix(by_density),
        }

    def _compute_jacobian(
        self, input_names: Iterable[str] = (), output_names: Iterable[str] = ()
    ) -> None:
        """Every row: for small grids only."""
        rows = np.arange(self.problem.elements)
        self.jac = {"stress": self.compute_jacobian_rows("stress", rows, self.io.data)}


class VolumeDiscipline(Discipline):  # type: ignore[misc]
    """``volume``, the volume fraction of the densities ``x``.

    Args:
        problem: The topology problem.
    """

    def __init__(self, problem: StressTopology) -> None:
        super().__init__("Volume")
        self.problem = problem
        self.io.input_grammar.update_from_data({"x": problem.x0.copy()})
        self.io.output_grammar.update_from_data({"volume": np.zeros(1)})
        self.io.input_grammar.defaults = {"x": problem.x0.copy()}

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        filtered = self.problem.filter @ np.asarray(input_data["x"], dtype=float)
        return {"volume": np.array([filtered.mean()])}

    def _compute_jacobian(
        self, input_names: Iterable[str] = (), output_names: Iterable[str] = ()
    ) -> None:
        x = np.asarray(self.io.data["x"], dtype=float)
        self.jac = {"volume": {"x": self.problem.objective_gradient(x)[None, :]}}


def split_disciplines(
    problem: StressTopology, products: bool
) -> tuple[DisplacementsDiscipline, StressesDiscipline, VolumeDiscipline]:
    """The disciplines of the split problem.

    Args:
        problem: The topology problem.
        products: Whether the displacements give their vector-Jacobian
            products; otherwise GEMSEO forms their Jacobian.
    """
    kind = AdjointDisplacementsDiscipline if products else DisplacementsDiscipline
    return kind(problem), StressesDiscipline(problem), VolumeDiscipline(problem)
