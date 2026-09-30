"""The topology problem as GEMSEO disciplines (spec § 9).

- ``StressDiscipline``: the volume fraction and the stress constraints of the
  elements (``stress``, ``sigma / sigma_lim - 1``), giving the rows of the stresses by
  adjoint (``RowJacobian``) and their directional derivatives (``TangentJacobian``):
  for ``LSO_MMA`` and ``LSO_GCMMA``;
- ``AggregatedStressDiscipline``: the volume fraction and a p-norm of the
  stresses, one constraint, with their whole gradients: for the optimizers
  that cannot take one constraint per element (``NLOPT_MMA``).

``StressDiscipline`` describes its physics to the Claude copilot
(``physical_description``, ``physical_fields``).

GEMSEO imports these modules only when the benchmarks are run.
"""

from collections.abc import Iterable
from collections.abc import Mapping
from typing import Any

import numpy as np
from gemseo.core.discipline import Discipline
from scipy import sparse

from gemseo_lso.benchmarks.topology.model import StressTopology


class StressDiscipline(Discipline):  # type: ignore[misc]
    """``volume`` and ``stress`` of the densities ``x``.

    Args:
        problem: The topology problem.
    """

    def __init__(self, problem: StressTopology) -> None:
        super().__init__("Structure")
        self.problem = problem
        size = problem.elements
        self.io.input_grammar.update_from_data({"x": problem.x0.copy()})
        self.io.output_grammar.update_from_data(
            {"volume": np.zeros(1), "stress": np.zeros(size)}
        )
        self.io.input_grammar.defaults = {"x": problem.x0.copy()}

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        volume, stress, _ = self.problem.values(input_data["x"])
        return {"volume": np.array([volume]), "stress": stress}

    def _compute_jacobian(
        self, input_names: Iterable[str] = (), output_names: Iterable[str] = ()
    ) -> None:
        x = self.io.data["x"]
        names = list(output_names) or ["volume", "stress"]
        self.jac = {}
        if "volume" in names:
            self.jac["volume"] = {"x": self.problem.objective_gradient(x)[None, :]}
        if "stress" in names:
            # Every row: for small grids only.
            rows = np.arange(self.problem.elements)
            self.jac["stress"] = {"x": self.problem.constraint_rows(x, rows)}

    def compute_jacobian_rows(
        self, output_name: str, rows: np.ndarray, input_data: Mapping[str, Any]
    ) -> dict[str, Any]:
        """The rows of the stresses, by adjoint."""
        return {"x": self.problem.constraint_rows(input_data["x"], rows)}

    def compute_directional_derivatives(
        self,
        output_name: str,
        directions: Mapping[str, np.ndarray],
        input_data: Mapping[str, Any],
    ) -> np.ndarray:
        """The directional derivatives of the stresses, by the direct mode."""
        return self.problem.directional_derivatives(
            input_data["x"], sparse.csc_matrix(directions["x"])
        )

    def physical_description(self) -> dict[str, Any]:
        """The physics of the structure, for the Claude copilot."""
        return self.problem.physical_description()

    def physical_fields(self, input_data: Mapping[str, Any]) -> dict[str, np.ndarray]:
        """The physical fields of the elements at a point, for the Claude copilot."""
        return self.problem.physical_fields(np.asarray(input_data["x"], dtype=float))


class AggregatedStressDiscipline(Discipline):  # type: ignore[misc]
    """``volume`` and ``stress_norm``, a p-norm of the stress constraints.

    Args:
        problem: The topology problem.
        power: The power of the p-norm.
    """

    def __init__(self, problem: StressTopology, power: float = 8.0) -> None:
        super().__init__("AggregatedStructure")
        self.problem = problem
        self.power = power
        self.io.input_grammar.update_from_data({"x": problem.x0.copy()})
        self.io.output_grammar.update_from_data(
            {"volume": np.zeros(1), "stress_norm": np.zeros(1)}
        )
        self.io.input_grammar.defaults = {"x": problem.x0.copy()}

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        x = input_data["x"]
        volume, _, _ = self.problem.values(x)
        norm, _ = self.problem.aggregated(x, self.power)
        return {"volume": np.array([volume]), "stress_norm": np.array([norm])}

    def _compute_jacobian(
        self, input_names: Iterable[str] = (), output_names: Iterable[str] = ()
    ) -> None:
        x = self.io.data["x"]
        _, gradient = self.problem.aggregated(x, self.power)
        self.jac = {
            "volume": {"x": self.problem.objective_gradient(x)[None, :]},
            "stress_norm": {"x": gradient[None, :]},
        }
