"""GEMSEO disciplines around the synthetic problem, for the plugin's tests."""

from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
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


class PlainLoads(Discipline):
    """``y = y0 + A u + 0.1 (A u)²``, differentiated by GEMSEO only.

    Stands for the internal loads of a structure: ``A`` is sparse, every output
    depends on a few inputs; ``y0`` are the external loads.

    Args:
        matrix: ``A``, of shape ``(outputs, inputs)``.
        input_name: ``u``, a design variable or an upstream output.
        output_name: ``y``.
        name: The name of the discipline.
    """

    def __init__(
        self,
        matrix: sparse.csr_matrix,
        input_name: str = "x",
        output_name: str = "loads",
        name: str = "",
    ) -> None:
        super().__init__(name or type(self).__name__)
        self.matrix = sparse.csr_matrix(matrix)
        self.input_name = input_name
        self.output_name = output_name
        rows, columns = matrix.shape
        self.external = 1.0 + 0.1 * np.arange(rows) / rows
        self.jacobians = 0
        """Whole Jacobians computed."""
        self.products = 0
        """Calls of ``compute_vector_jacobian_products``."""
        self.product_rows: list[int] = []
        """The rows of each call."""
        self.tangents = 0
        """Directions of ``compute_directional_derivatives``."""
        start = np.full(columns, 0.5)
        self.io.input_grammar.update_from_data({input_name: start})
        self.io.output_grammar.update_from_data({output_name: np.zeros(rows)})
        self.io.input_grammar.defaults = {input_name: start.copy()}

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        linear = self.matrix @ input_data[self.input_name]
        return {self.output_name: self.external + linear + 0.1 * linear**2}

    def derivative(self, u: np.ndarray) -> sparse.csr_matrix:
        """``dy/du = diag(1 + 0.2 A u) A``."""
        factor = 1.0 + 0.2 * (self.matrix @ u)
        return sparse.csr_matrix(sparse.diags(factor) @ self.matrix)

    def _compute_jacobian(
        self, input_names: Iterable[str] = (), output_names: Iterable[str] = ()
    ) -> None:
        self.jacobians += 1
        jacobian = self.derivative(self.io.data[self.input_name])
        self.jac = {self.output_name: {self.input_name: jacobian}}


class Loads(PlainLoads):
    """``PlainLoads`` giving vector-Jacobian products and directional derivatives."""

    def compute_vector_jacobian_products(
        self,
        weights: Mapping[str, Any],
        input_data: Mapping[str, Any],
        input_names: Sequence[str],
    ) -> dict[str, Any]:
        self.products += 1
        block = weights[self.output_name]
        self.product_rows.append(block.shape[0])
        assert list(input_names) == [self.input_name]
        derivative = self.derivative(input_data[self.input_name])
        return {self.input_name: sparse.csr_matrix(block) @ derivative}

    def compute_directional_derivatives(
        self,
        output_name: str,
        directions: Mapping[str, np.ndarray],
        input_data: Mapping[str, Any],
    ) -> np.ndarray:
        self.tangents += directions[self.input_name].shape[1]
        derivative = self.derivative(input_data[self.input_name])
        return np.asarray(derivative @ directions[self.input_name])


class Stresses(Discipline):
    """``g = (Σ_k B_k y_k) / x - 1``: one constraint per item, ``x`` its size.

    Gives its rows (``RowJacobian``) and directional derivatives; GEMSEO's
    whole Jacobian, counted, otherwise.

    Args:
        loads: ``B_k`` by name of the loads ``y_k`` it reads, ``(items, size)``.
        output_name: ``g``.
        name: The name of the discipline.
    """

    def __init__(
        self,
        loads: Mapping[str, sparse.csr_matrix],
        output_name: str = "stress",
        name: str = "",
    ) -> None:
        super().__init__(name or type(self).__name__)
        self.loads = {key: sparse.csr_matrix(value) for key, value in loads.items()}
        self.output_name = output_name
        items = next(iter(self.loads.values())).shape[0]
        self.jacobians = 0
        data = {"x": np.full(items, 0.5)}
        data.update({key: np.ones(b.shape[1]) for key, b in self.loads.items()})
        self.io.input_grammar.update_from_data(data)
        self.io.output_grammar.update_from_data({output_name: np.zeros(items)})
        self.io.input_grammar.defaults = {key: v.copy() for key, v in data.items()}

    def _force(self, data: Mapping[str, Any]) -> np.ndarray:
        force = np.zeros(next(iter(self.loads.values())).shape[0])
        for key, b in self.loads.items():
            force = force + b @ data[key]
        return force

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        return {self.output_name: self._force(input_data) / input_data["x"] - 1.0}

    def blocks(self, rows: np.ndarray, data: Mapping[str, Any]) -> dict[str, Any]:
        """The rows of the constraint, by input name."""
        x = data["x"]
        force = self._force(data)
        k = len(rows)
        result: dict[str, Any] = {
            "x": sparse.csr_matrix(
                (-force[rows] / x[rows] ** 2, (np.arange(k), rows)), shape=(k, x.size)
            )
        }
        for key, b in self.loads.items():
            result[key] = sparse.csr_matrix(sparse.diags(1 / x[rows]) @ b[rows])
        return result

    def _compute_jacobian(
        self, input_names: Iterable[str] = (), output_names: Iterable[str] = ()
    ) -> None:
        self.jacobians += 1
        rows = np.arange(self.io.data["x"].size)
        self.jac = {self.output_name: self.blocks(rows, self.io.data)}

    def compute_jacobian_rows(
        self, output_name: str, rows: np.ndarray, input_data: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self.blocks(rows, input_data)

    def compute_directional_derivatives(
        self,
        output_name: str,
        directions: Mapping[str, np.ndarray],
        input_data: Mapping[str, Any],
    ) -> np.ndarray:
        rows = np.arange(input_data["x"].size)
        products = np.zeros((rows.size, directions["x"].shape[1]))
        for key, block in self.blocks(rows, input_data).items():
            products += block @ directions[key]
        return products


class AdjointStresses(Discipline):
    """``Stresses`` giving vector-Jacobian products instead of its rows.

    Args:
        loads: ``B_k`` by name of the loads ``y_k`` it reads, ``(items, size)``.
        output_name: ``g``.
    """

    def __init__(
        self, loads: Mapping[str, sparse.csr_matrix], output_name: str = "stress"
    ) -> None:
        super().__init__("AdjointStresses")
        self.stresses = Stresses(loads, output_name)
        self.output_name = output_name
        self.io.input_grammar = self.stresses.io.input_grammar
        self.io.output_grammar = self.stresses.io.output_grammar

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        return self.stresses._run(input_data)

    def compute_vector_jacobian_products(
        self,
        weights: Mapping[str, Any],
        input_data: Mapping[str, Any],
        input_names: Sequence[str],
    ) -> dict[str, Any]:
        rows = np.arange(input_data["x"].size)
        weight = sparse.csr_matrix(weights[self.output_name])
        return {
            key: weight @ block
            for key, block in self.stresses.blocks(rows, input_data).items()
            if key in input_names
        }


class Mass(Discipline):
    """``mass = Σ x``: the objective, independent of the loads."""

    def __init__(self, size: int) -> None:
        super().__init__("Mass")
        self.io.input_grammar.update_from_data({"x": np.full(size, 0.5)})
        self.io.output_grammar.update_from_data({"mass": np.zeros(1)})
        self.io.input_grammar.defaults = {"x": np.full(size, 0.5)}

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        return {"mass": np.array([input_data["x"].sum()])}

    def _compute_jacobian(
        self, input_names: Iterable[str] = (), output_names: Iterable[str] = ()
    ) -> None:
        self.jac = {"mass": {"x": np.ones((1, self.io.data["x"].size))}}


class Work(Discipline):
    """``work = Σ x + c Σ y²``: an objective read from the loads ``y``.

    Differentiated by GEMSEO only; counts its Jacobians.

    Args:
        size: The size of ``x``.
        loads: The size of ``y``.
        factor: ``c``.
    """

    def __init__(self, size: int, loads: int, factor: float = 0.01) -> None:
        super().__init__("Work")
        self.factor = factor
        self.jacobians = 0
        data = {"x": np.full(size, 0.5), "loads": np.ones(loads)}
        self.io.input_grammar.update_from_data(data)
        self.io.output_grammar.update_from_data({"work": np.zeros(1)})
        self.io.input_grammar.defaults = {key: v.copy() for key, v in data.items()}

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        loads = input_data["loads"]
        return {"work": np.array([input_data["x"].sum() + self.factor * loads @ loads])}

    def _compute_jacobian(
        self, input_names: Iterable[str] = (), output_names: Iterable[str] = ()
    ) -> None:
        self.jacobians += 1
        x, loads = self.io.data["x"], self.io.data["loads"]
        self.jac = {
            "work": {
                "x": np.ones((1, x.size)),
                "loads": 2 * self.factor * loads[None, :],
            }
        }


def coupling(rows: int, columns: int, seed: int) -> sparse.csr_matrix:
    """A sparse non-negative ``A`` of small entries: each output reads 3 inputs."""
    rng = np.random.default_rng(seed)
    picked = np.stack([rng.permutation(columns)[:3] for _ in range(rows)])
    values = 0.1 * rng.random((rows, 3))
    return sparse.csr_matrix(
        (values.ravel(), (np.repeat(np.arange(rows), 3), picked.ravel())),
        shape=(rows, columns),
    )


def local_reading(items: int, components: int) -> sparse.csr_matrix:
    """``B``: item ``i`` reads the loads ``2i`` and ``2i + 1`` (modulo their number)."""
    rows = np.repeat(np.arange(items), 2)
    columns = np.stack([2 * np.arange(items), 2 * np.arange(items) + 1], axis=1)
    return sparse.csr_matrix(
        (np.full(2 * items, 0.5), (rows, columns.ravel() % components)),
        shape=(items, components),
    )
