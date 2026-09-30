"""GEMSEO disciplines around the synthetic problem, for the plugin's tests."""

from collections.abc import Iterable
from collections.abc import Mapping
from typing import Any

import numpy as np
from gemseo.core.discipline import Discipline
from scipy import sparse

from gemseo_lso.benchmarks.synthetic import LocalConstraints


class Local(Discipline):
    """``f = ||x - t||² / 2`` and ``g = A x - b``, the negated ``minus_g``.

    GEMSEO differentiates it in full (``g`` sparse, or dense with ``dense``).

    Args:
        problem: The synthetic problem.
        input_name: The name of its input, ``x`` or an upstream output.
        dense: Whether its Jacobian is dense.
    """

    def __init__(
        self, problem: LocalConstraints, input_name: str = "x", dense: bool = False
    ) -> None:
        super().__init__(type(self).__name__)
        self.problem = problem
        self.input_name = input_name
        self.dense = dense
        self.full_jacobians = 0
        size = problem.x0.size
        self.io.input_grammar.update_from_data({input_name: problem.x0.copy()})
        self.io.output_grammar.update_from_data(
            {"f": np.zeros(1), "g": np.zeros(size), "minus_g": np.zeros(size)}
        )
        self.io.input_grammar.defaults = {input_name: problem.x0.copy()}

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        objective, constraints, _ = self.problem.values(input_data[self.input_name])
        return {"f": np.array([objective]), "g": constraints, "minus_g": -constraints}

    def _compute_jacobian(
        self, input_names: Iterable[str] = (), output_names: Iterable[str] = ()
    ) -> None:
        x = self.io.data[self.input_name]
        jacobian = self.problem.jacobian
        if self.dense:
            jacobian = jacobian.toarray()
        full = {
            "f": {self.input_name: self.problem.objective_gradient(x)[None, :]},
            "g": {self.input_name: jacobian},
            "minus_g": {self.input_name: -jacobian},
        }
        names = list(output_names) or list(full)
        # Only the Jacobians of the constraints count: GEMSEO asks for the
        # gradient of the objective alone too.
        self.full_jacobians += any(name != "f" for name in names)
        self.jac = {name: full[name] for name in names}


class RowsLocal(Local):
    """``Local``, giving the rows of its constraints on request."""

    def compute_jacobian_rows(
        self, output_name: str, rows: np.ndarray, input_data: Mapping[str, Any]
    ) -> dict[str, Any]:
        block = self.problem.constraint_rows(input_data[self.input_name], rows)
        return {self.input_name: -block if output_name == "minus_g" else block}


class TangentLocal(Local):
    """``Local``, giving directional derivatives of its constraints."""

    def compute_directional_derivatives(
        self,
        output_name: str,
        directions: Mapping[str, np.ndarray],
        input_data: Mapping[str, Any],
    ) -> np.ndarray:
        products = self.problem.jacobian @ directions[self.input_name]
        self.problem.products += directions[self.input_name].shape[1]
        return -products if output_name == "minus_g" else products


class RowsTangentLocal(RowsLocal, TangentLocal):
    """``Local``, giving rows and directional derivatives."""


class Halved(Discipline):
    """``x = u / 2``, upstream of ``Local(input_name="x")``."""

    def __init__(self, size: int) -> None:
        super().__init__("Halved")
        self.io.input_grammar.update_from_data({"u": np.ones(size)})
        self.io.output_grammar.update_from_data({"x": np.zeros(size)})
        self.io.input_grammar.defaults = {"u": np.ones(size)}
        self._size = size

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        return {"x": input_data["u"] / 2}

    def _compute_jacobian(
        self, input_names: Iterable[str] = (), output_names: Iterable[str] = ()
    ) -> None:
        self.jac = {"x": {"u": sparse.csr_matrix(sparse.eye(self._size) / 2)}}


class Feedback(Discipline):
    """``w = f``: couples a discipline reading ``w`` to ``Local``."""

    def __init__(self) -> None:
        super().__init__("Feedback")
        self.io.input_grammar.update_from_data({"f": np.zeros(1)})
        self.io.output_grammar.update_from_data({"w": np.zeros(1)})
        self.io.input_grammar.defaults = {"f": np.zeros(1)}

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        return {"w": np.array(input_data["f"])}

    def _compute_jacobian(
        self, input_names: Iterable[str] = (), output_names: Iterable[str] = ()
    ) -> None:
        self.jac = {"w": {"f": np.ones((1, 1))}}


class CoupledLocal(RowsLocal):
    """``RowsLocal`` reading ``w``, computed from its own ``f``."""

    def __init__(self, problem: LocalConstraints) -> None:
        super().__init__(problem)
        self.io.input_grammar.update_from_data({"w": np.zeros(1)})
        self.io.input_grammar.defaults["w"] = np.zeros(1)

    def _compute_jacobian(
        self, input_names: Iterable[str] = (), output_names: Iterable[str] = ()
    ) -> None:
        super()._compute_jacobian(input_names, output_names)
        for name, block in self.jac.items():
            block["w"] = np.zeros((1 if name == "f" else self.problem.x0.size, 1))
