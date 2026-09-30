"""Stress-constrained topology optimization in 2D plane stress (spec § 9).

Minimize the volume of a structure under a von Mises stress constraint per
element: a density ``x`` per element, filtered (``x̃ = H x``, a cone of radius
``filter_radius``), a SIMP stiffness ``E(x̃) = E_min + x̃^p (E_0 - E_min)`` and a
relaxed stress ``sigma(x̃) = x̃^q sigma_vm(u)`` (the qp-approach, ``q < p``: without it,
the stress of a vanishing element does not vanish, and the optimum is
singular). The constraint of element ``e`` is ``sigma_e / sigma_lim - 1 <= 0``.

Bilinear square elements of unit size on a regular grid; the stiffness matrix
is factorized once per point (SuperLU) and reused:

- **rows by adjoint**: the gradients of a batch of stress constraints cost one
  solve with as many right-hand sides;
- **directional derivatives by the direct mode**: a batch of directions costs
  one solve with as many right-hand sides.

It describes its physics to the Claude copilot (``physical_description``,
``physical_fields``): the grid, the supports, the loads, the geometric features,
and the physical density, stress, strain energy, principal stress sign and
displacement of each element.

Both use the sparse matrix ``S`` (degrees of freedom × elements) whose column
``j`` is ``∂K/∂x̃_j u``: the derivative of the residual ``K u - f`` with respect
to the density of element ``j``.

The stresses depend on the whole structure through the displacements: every
row is dense, with entries decaying with the distance to the element. The
pattern of the colored modes (``sparsity``) keeps the elements within a radius.

Example:
    >>> import numpy as np
    >>> from gemseo_lso.benchmarks.topology.cases import cantilever
    >>> problem = cantilever(8, 4)
    >>> volume, stresses, _ = problem.values(problem.x0)
    >>> round(volume, 3), stresses.shape
    (1.0, (32,))
"""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from dataclasses import field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import sparse
from scipy.sparse.linalg import splu
from scipy.spatial import cKDTree

from gemseo_lso.core.arrays import Array
from gemseo_lso.core.arrays import Indices

POISSON = 0.3
E_MIN = 1e-9
"""The stiffness of void, relative to the solid (keeps ``K`` invertible)."""

THREADS = os.cpu_count() or 1
"""SuperLU releases the GIL: the right-hand sides are solved on every core."""

GAUSS = (-1 / np.sqrt(3), 1 / np.sqrt(3))
CORNERS = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], dtype=float)
"""The nodes of an element, counterclockwise from the lower left one."""


def elasticity() -> Array:
    """The plane-stress elasticity matrix of the solid (``E_0 = 1``)."""
    nu = POISSON
    return np.array([[1, nu, 0], [nu, 1, 0], [0, 0, (1 - nu) / 2]]) / (1 - nu**2)


def strain_matrix(xi: float, eta: float) -> Array:
    """``B`` (3 × 8) of a unit square element at a point of its reference square."""
    derivatives = np.array(
        [
            [CORNERS[k, 0] * (1 + CORNERS[k, 1] * eta) / 4 for k in range(4)],
            [CORNERS[k, 1] * (1 + CORNERS[k, 0] * xi) / 4 for k in range(4)],
        ]
    )
    # The element is the square [0, 1]²: dx/dξ = 1/2.
    derivatives *= 2
    matrix = np.zeros((3, 8))
    matrix[0, 0::2] = derivatives[0]
    matrix[1, 1::2] = derivatives[1]
    matrix[2, 0::2] = derivatives[1]
    matrix[2, 1::2] = derivatives[0]
    return matrix


def solve(solver: object, rhs: Array) -> Array:
    """``K⁻¹ rhs``, the columns of ``rhs`` shared out between threads."""
    columns = rhs.shape[1] if rhs.ndim == 2 else 1
    if columns < 2 * THREADS:
        return np.asarray(solver.solve(rhs))  # type: ignore[attr-defined]
    parts = np.array_split(rhs, THREADS, axis=1)
    with ThreadPoolExecutor(THREADS) as pool:
        solved = list(pool.map(solver.solve, parts))  # type: ignore[attr-defined]
    return np.hstack(solved)


def element_stiffness() -> Array:
    """The stiffness matrix (8 × 8) of a solid unit square element, 2 × 2 Gauss."""
    matrix = np.zeros((8, 8))
    for xi in GAUSS:
        for eta in GAUSS:
            b = strain_matrix(xi, eta)
            matrix += b.T @ elasticity() @ b / 4  # The Jacobian of the map: 1/4.
    return matrix


@dataclass
class _State:
    """What the model computes at a point, reused by the rows and directions."""

    x: Array
    filtered: Array
    displacements: Array
    solver: object
    von_mises: Array
    """The von Mises stress of the solid, per element."""

    stress_rows: sparse.csc_matrix
    """Column ``e``: ``∂g_e/∂u``, over the free degrees of freedom."""

    residual: sparse.csc_matrix
    """``S``, column ``j``: ``∂K/∂x̃_j u`` over the free degrees of freedom."""

    direct: Array
    """``∂g_e/∂x̃_e`` through the relaxation, per element."""


@dataclass
class StressTopology:
    """The problem, seen by the optimizer through its protocol (spec § 5).

    Args:
        mask: The elements of the grid (``True``), of shape ``(ny, nx)``, row 0
            at the bottom.
        fixed: The fixed degrees of freedom, as ``2 * node + direction``.
        loads: The nodal forces, by degree of freedom.
        stress_limit: ``sigma_lim``.
        filter_radius: The radius of the density filter, in elements.
        penalty: ``p`` of SIMP.
        relaxation: ``q`` of the relaxed stress.
        radius: The radius of the pattern of a stress constraint, in elements.
        summary: What the structure is, in a few sentences.
        features: The geometric features worth naming, each a ``name``, the
            ``node`` of the grid where it is (``(column, row)``) and a ``note``.
    """

    mask: NDArray[np.bool_]
    fixed: NDArray[np.intp]
    loads: dict[int, float]
    stress_limit: float
    filter_radius: float = 1.5
    penalty: float = 3.0
    relaxation: float = 0.5
    radius: float = 6.0
    summary: str = ""
    features: tuple[dict[str, Any], ...] = ()
    evaluations: int = 0
    rows: int = 0
    """The constraint gradients given."""

    products: int = 0
    """The directional derivatives given."""

    solves: int = 0
    """The right-hand sides solved, adjoint and direct."""

    _state: _State | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _, nx = self.mask.shape
        rows, columns = np.nonzero(self.mask)
        self.centers = np.stack([columns + 0.5, rows + 0.5], axis=1)
        grid_nodes = np.stack(
            [
                rows * (nx + 1) + columns,
                rows * (nx + 1) + columns + 1,
                (rows + 1) * (nx + 1) + columns + 1,
                (rows + 1) * (nx + 1) + columns,
            ],
            axis=1,
        )
        used, nodes = np.unique(grid_nodes, return_inverse=True)
        self.grid_nodes = used
        """The node of the grid of each node of the mesh."""
        nodes = nodes.reshape(-1, 4)
        self.dofs = np.empty((nodes.shape[0], 8), dtype=np.intp)
        self.dofs[:, 0::2] = 2 * nodes
        self.dofs[:, 1::2] = 2 * nodes + 1
        size = 2 * used.size
        self.size = size
        position = {int(node): index for index, node in enumerate(used)}
        fixed = [
            2 * position[int(d) // 2] + int(d) % 2
            for d in self.fixed
            if int(d) // 2 in position
        ]
        self.free = np.setdiff1d(np.arange(size), fixed)
        self._free_index = np.full(size, -1, dtype=np.intp)
        self._free_index[self.free] = np.arange(self.free.size)
        self.force = np.zeros(size)
        for dof, value in self.loads.items():
            self.force[2 * position[int(dof) // 2] + int(dof) % 2] += value
        self.stiffness = element_stiffness()
        self.center_strain = strain_matrix(0.0, 0.0)
        self.filter = self._filter()
        elements = self.dofs.shape[0]
        self._rows_k = np.repeat(self.dofs, 8, axis=1).ravel()
        self._columns_k = np.tile(self.dofs, 8).ravel()
        self._element_rows = np.repeat(np.arange(elements), 8)
        self._x0 = np.ones(elements)

    @property
    def elements(self) -> int:
        """The number of elements: of design variables and of constraints."""
        return int(self.dofs.shape[0])

    @property
    def x0(self) -> Array:
        """Full density."""
        return self._x0

    @property
    def lower(self) -> Array:
        """0."""
        return np.zeros(self.elements)

    @property
    def upper(self) -> Array:
        """1."""
        return np.ones(self.elements)

    def _filter(self) -> sparse.csr_matrix:
        """``H``, rows normalized: ``x̃_i = Σ_j w_ij x_j / Σ_j w_ij``, cone weights."""
        tree = cKDTree(self.centers)
        distances = tree.sparse_distance_matrix(
            tree, self.filter_radius, output_type="coo_matrix"
        )
        weights = sparse.csr_matrix(
            (self.filter_radius - distances.data, (distances.row, distances.col)),
            shape=(self.elements, self.elements),
        )
        weights = weights + self.filter_radius * sparse.eye(self.elements, format="csr")
        totals = np.asarray(weights.sum(axis=1)).ravel()
        return sparse.csr_matrix(sparse.diags(1 / totals) @ weights)

    def state(self, x: Array) -> _State:
        """Solve the finite-element problem at ``x`` (once per point)."""
        if self._state is not None and np.array_equal(self._state.x, x):
            return self._state
        filtered = self.filter @ x
        p, q = self.penalty, self.relaxation
        young = E_MIN + filtered**p * (1 - E_MIN)
        values = (self.stiffness.ravel()[None, :] * young[:, None]).ravel()
        matrix = sparse.csc_matrix(
            (values, (self._rows_k, self._columns_k)), shape=(self.size, self.size)
        )
        free = self.free
        solver = splu(matrix[free][:, free].tocsc(), permc_spec="MMD_AT_PLUS_A")
        displacements = np.zeros(self.size)
        displacements[free] = solver.solve(self.force[free])
        element_u = displacements[self.dofs]  # (elements, 8)
        stress = element_u @ (elasticity() @ self.center_strain).T  # (elements, 3)
        sx, sy, txy = stress.T
        von_mises = np.sqrt(np.maximum(sx**2 + sy**2 - sx * sy + 3 * txy**2, 1e-30))
        relaxed = np.maximum(filtered, 0.0) ** q
        # ∂g_e/∂u_e = x̃_e^q ∂sigma_vm/∂sigma D B / sigma_lim, over the dofs of e.
        dvm = np.stack(
            [
                (2 * sx - sy) / (2 * von_mises),
                (2 * sy - sx) / (2 * von_mises),
                3 * txy / von_mises,
            ],
            axis=1,
        )
        weights = (dvm @ elasticity() @ self.center_strain) * (
            relaxed / self.stress_limit
        )[:, None]
        stress_rows = self._scatter(weights)
        derivative = p * np.maximum(filtered, 0.0) ** (p - 1) * (1 - E_MIN)
        forces = element_u @ self.stiffness.T * derivative[:, None]  # ∂K/∂x̃_j u_j
        residual = self._scatter(forces)
        direct = np.where(
            filtered > 0,
            q * np.maximum(filtered, 1e-12) ** (q - 1) * von_mises / self.stress_limit,
            0.0,
        )
        self._state = _State(
            x=x.copy(),
            filtered=filtered,
            displacements=displacements,
            solver=solver,
            von_mises=von_mises,
            stress_rows=stress_rows,
            residual=residual,
            direct=direct,
        )
        return self._state

    def _scatter(self, blocks: Array) -> sparse.csc_matrix:
        """Blocks (elements × 8) as a matrix (free dofs × elements)."""
        rows = self._free_index[self.dofs.ravel()]
        keep = rows >= 0
        return sparse.csc_matrix(
            (blocks.ravel()[keep], (rows[keep], self._element_rows[keep])),
            shape=(self.free.size, self.elements),
        )

    def stresses(self, x: Array) -> Array:
        """The relaxed von Mises stress of each element."""
        state = self.state(x)
        return np.maximum(state.filtered, 0.0) ** self.relaxation * state.von_mises

    def values(self, x: Array) -> tuple[float, Array, Array]:
        """The volume fraction, the stress constraints; no equality."""
        self.evaluations += 1
        state = self.state(x)
        stresses = np.maximum(state.filtered, 0.0) ** self.relaxation * state.von_mises
        volume = float(state.filtered.mean())
        return volume, stresses / self.stress_limit - 1, np.zeros(0)

    def objective_gradient(self, x: Array) -> Array:
        """Of the volume fraction: ``Hᵀ 1 / n``."""
        return np.asarray(self.filter.T @ np.full(self.elements, 1 / self.elements))

    def constraint_rows(self, x: Array, rows: Indices) -> Array:
        """Rows by adjoint: one solve with ``len(rows)`` right-hand sides."""
        self.rows += len(rows)
        self.solves += len(rows)
        state = self.state(x)
        seeds = state.stress_rows[:, rows].toarray()
        adjoints = solve(state.solver, seeds)  # (free dofs, rows)
        # dg/dx̃ = direct - λᵀ S, then through the filter: dg/dx = dg/dx̃ H.
        filtered_rows = -(state.residual.T @ adjoints).T
        filtered_rows[np.arange(len(rows)), rows] += state.direct[rows]
        return np.asarray(sparse.csr_matrix(self.filter.T) @ filtered_rows.T).T

    def directional_derivatives(self, x: Array, directions: sparse.csc_matrix) -> Array:
        """By the direct mode: one solve with as many right-hand sides as directions."""
        count = directions.shape[1]
        self.products += count
        self.solves += count
        state = self.state(x)
        filtered: Array = np.asarray(
            sparse.csr_matrix(self.filter @ directions).toarray()
        )
        motions = -solve(state.solver, np.asarray(state.residual @ filtered))
        products: Array = np.asarray(state.stress_rows.T @ motions)
        return products + state.direct[:, None] * filtered

    def equality_rows(self, x: Array) -> Array:
        """No equality constraint."""
        return np.zeros((0, self.elements))

    def sparsity(self) -> sparse.csr_matrix:
        """The elements within ``radius`` of each element (and of the filter)."""
        tree = cKDTree(self.centers)
        reach = self.radius + self.filter_radius
        pairs = tree.sparse_distance_matrix(tree, reach, output_type="coo_matrix")
        pattern = sparse.csr_matrix(
            (np.ones(pairs.nnz, dtype=bool), (pairs.row, pairs.col)),
            shape=(self.elements, self.elements),
        )
        return sparse.csr_matrix(
            pattern + sparse.eye(self.elements, dtype=bool, format="csr")
        )

    def physical_description(self) -> dict[str, Any]:
        """The physics of the problem, for the Claude copilot.

        The grid of the elements, row 0 at the bottom; the design variable ``x``
        and the constraint ``stress`` laid on it, one component per element;
        the supports, the loads and the features on the elements touching
        their nodes; the fields of ``physical_fields``.
        """
        rows, columns = self.mask.shape
        element_rows, element_columns = np.nonzero(self.mask)
        cells = (element_rows * columns + element_columns).tolist()
        fixed = sorted({int(dof) // 2 for dof in self.fixed})
        directions = {int(dof) % 2 for dof in self.fixed}
        blocked = " and ".join("xy"[direction] for direction in sorted(directions))
        loaded: dict[int, Array] = {}
        for dof, value in self.loads.items():
            vector = loaded.setdefault(int(dof) // 2, np.zeros(2))
            vector[int(dof) % 2] += value
        total = np.sum(list(loaded.values()), axis=0)
        magnitude = float(np.linalg.norm(total))
        physics = (
            "2D linear elasticity in plane stress, on a grid of unit square "
            "bilinear elements (Poisson ratio 0.3, Young modulus 1 for the "
            "solid). A density x per element, in [0, 1], is filtered by a cone "
            f"of radius {self.filter_radius:g} elements into the physical "
            f"density. The stiffness is 1e-9 + density^{self.penalty:g} (SIMP): "
            "intermediate densities give little stiffness for their volume. "
            "Objective: the volume fraction, the mean physical density, "
            "minimized. Constraints: one per element, its von Mises stress "
            f"relaxed by the density, density^{self.relaxation:g} sigma_vm "
            "(without the relaxation, a vanishing element keeps a finite stress "
            "and the optimum is singular), relative to the limit "
            f"{self.stress_limit:g}: sigma / sigma_lim - 1 <= 0."
        )
        return {
            "summary": f"{self.summary} {physics}".strip(),
            "grid": {
                "rows": rows,
                "columns": columns,
                "cell_size": 1.0,
                "unit": "element width",
            },
            "variable": "x",
            "variable_cells": cells,
            "constraint_cells": {"stress": cells},
            "features": [
                {
                    "name": feature["name"],
                    "cells": self._cells_at([self._node(*feature["node"])]),
                    "note": feature.get("note", ""),
                }
                for feature in self.features
            ],
            "supports": [
                {
                    "name": "clamped nodes",
                    "cells": self._cells_at(fixed),
                    "blocks": blocked,
                }
            ],
            "loads": [
                {
                    "name": "load",
                    "cells": self._cells_at(list(loaded)),
                    "direction": (total / magnitude).tolist() if magnitude else [0, 0],
                    "magnitude": magnitude,
                    "unit": "force (Young modulus 1, element width 1)",
                }
            ],
            "fields": [
                {
                    "name": "density",
                    "quantity": "physical density (the filtered x)",
                    "unit": "-",
                    "role": "density",
                    "reduce": "mean",
                    "reading": "0 void, 1 solid; between them the material is "
                    "penalized: it costs volume for little stiffness.",
                },
                {
                    "name": "stress_ratio",
                    "quantity": "relaxed von Mises stress over its limit",
                    "unit": "-",
                    "role": "stress_ratio",
                    "reduce": "max",
                    "reading": "above 1 the stress constraint of the element is "
                    "violated; near 1 it is active.",
                },
                {
                    "name": "strain_energy",
                    "quantity": "strain energy of the element",
                    "unit": "energy (Young modulus 1, element width 1)",
                    "role": "energy",
                    "reduce": "mean",
                    "reading": "where the load travels: high along the load "
                    "path, near zero in material that carries nothing.",
                },
                {
                    "name": "principal_sign",
                    "quantity": "sign of the principal stress of largest "
                    "magnitude, in the solid",
                    "unit": "-",
                    "role": "principal_sign",
                    "reduce": "mean",
                    "reading": "+1 tension, -1 compression: members in tension "
                    "and in compression, bending where both meet.",
                },
                {
                    "name": "displacement",
                    "quantity": "displacement magnitude",
                    "unit": "element width",
                    "role": "other",
                    "reduce": "max",
                    "reading": "how far the element moves under the load.",
                },
            ],
            "minimum_member_size": 2 * self.filter_radius,
        }

    def physical_fields(self, x: Array) -> dict[str, Array]:
        """The fields of ``physical_description`` at ``x``, one value per element."""
        state = self.state(x)
        density = np.maximum(state.filtered, 0.0)
        element_u = state.displacements[self.dofs]
        young = E_MIN + density**self.penalty * (1 - E_MIN)
        work = np.einsum("ei,ij,ej->e", element_u, self.stiffness, element_u)
        sx, sy, txy = (element_u @ (elasticity() @ self.center_strain).T).T
        center = (sx + sy) / 2
        radius = np.sqrt(((sx - sy) / 2) ** 2 + txy**2)
        larger = np.abs(center + radius) >= np.abs(center - radius)
        major = np.where(larger, center + radius, center - radius)
        motion = np.hypot(
            element_u[:, 0::2].mean(axis=1), element_u[:, 1::2].mean(axis=1)
        )
        return {
            "density": density,
            "stress_ratio": density**self.relaxation
            * state.von_mises
            / self.stress_limit,
            "strain_energy": 0.5 * young * work,
            "principal_sign": np.sign(major),
            "displacement": motion,
        }

    def _node(self, column: int, row: int) -> int:
        """The node of the grid at a column and a row of nodes."""
        return int(row * (self.mask.shape[1] + 1) + column)

    def _cells_at(self, nodes: list[int]) -> list[int]:
        """The cells of the elements touching some nodes of the grid."""
        rows, columns = self.mask.shape
        cells = set()
        for node in nodes:
            row, column = divmod(node, columns + 1)
            for r in (row - 1, row):
                for c in (column - 1, column):
                    if 0 <= r < rows and 0 <= c < columns and self.mask[r, c]:
                        cells.add(r * columns + c)
        return sorted(cells)

    def aggregated(self, x: Array, power: float = 8.0) -> tuple[float, Array]:
        """A p-norm of the stress constraints and its gradient, by one adjoint.

        ``(sum (sigma_e / sigma_lim)^P)^(1/P) - 1``: one constraint in place of all, for
        the optimizers that cannot take so many (``NLOPT_MMA``).
        """
        state = self.state(x)
        ratios = (
            np.maximum(state.filtered, 0.0) ** self.relaxation
            * state.von_mises
            / self.stress_limit
        )
        total = float(np.sum(ratios**power))
        norm = total ** (1 / power)
        weights = norm ** (1 - power) * ratios ** (power - 1)
        adjoint = solve(state.solver, np.asarray(state.stress_rows @ weights))
        self.solves += 1
        filtered = -(state.residual.T @ adjoint) + weights * state.direct
        return norm - 1, np.asarray(self.filter.T @ filtered)
