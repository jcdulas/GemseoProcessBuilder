"""Truss sizing problems of the literature, with their published optima.

The classic benchmarks of structural optimization (Schmit and Farshi 1974, then
many others; the values below are those tabulated by Kaveh and others, and
collected in arXiv:1306.1454): minimize the weight of a truss under stress and
displacement limits, the cross-sectional areas of groups of members being the
design variables. Units: inches, kips, ksi, pounds.

- the **10-bar** planar truss (10 variables), best known weight 5060.85 lb;
- the **25-bar** space tower (8 groups, 2 load cases), 545.16 lb;
- the **72-bar** space truss (16 groups, 2 load cases), 379.62 lb.

The geometry of each is a figure in the papers: it is rebuilt here, and checked
against the published optimal designs (their weight, and the constraints they
make active: ``tests/test_lso_literature.py``).

Example:
    >>> truss = ten_bar()
    >>> round(truss.weight(truss.published), 1)
    5060.8
"""

from dataclasses import dataclass
from dataclasses import field

import numpy as np
from numpy.typing import NDArray

from gemseo_lso.core.arrays import Array
from gemseo_lso.core.arrays import Indices
from gemseo_lso.core.problem import DenseProblem

YOUNG = 1.0e4
"""Young's modulus of the aluminium of all three, in ksi."""

DENSITY = 0.1
"""Its density, in lb/in³."""


@dataclass
class Truss:
    """A truss and the sizing problem on the groups of its members.

    Args:
        nodes: The coordinates of the nodes, ``(N, d)``.
        members: The nodes of each member, ``(M, 2)``, from 0.
        groups: The group of each member, from 0.
        fixed: Which coordinates of the nodes are held, ``(N, d)``.
        loads: The nodal forces of each load case, ``(N, d)`` each.
        stress_limits: The compressive and tensile limits of each group, ``(G, 2)``.
        displacement_limit: The largest displacement of a coordinate.
        limited: Which coordinates of the nodes the displacement limit holds
            for, ``(N, d)``; all the free ones by default.
        lower: The smallest area.
        upper: The largest area the optimizer may use (the papers have none).
        known: The published best weight, and where it comes from.
        published: The areas of a published optimal design (rounded to the
            digits of the papers).
    """

    nodes: Array
    members: Indices
    groups: Indices
    fixed: NDArray[np.bool_]
    loads: list[Array]
    stress_limits: Array
    displacement_limit: float
    limited: NDArray[np.bool_] | None = None
    lower: float = 0.1
    upper: float = 50.0
    known: tuple[float, str] = (0.0, "")
    published: Array = field(default_factory=lambda: np.zeros(0))
    evaluations: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.nodes = np.asarray(self.nodes, dtype=float)
        self.members = np.asarray(self.members, dtype=int)
        self.groups = np.asarray(self.groups, dtype=int)
        self.fixed = np.asarray(self.fixed, dtype=bool)
        self.size = int(self.groups.max()) + 1
        dimension = self.nodes.shape[1]
        self.free = np.flatnonzero(~self.fixed.ravel())
        start, end = self.nodes[self.members[:, 0]], self.nodes[self.members[:, 1]]
        self.lengths = np.linalg.norm(end - start, axis=1)
        cosines = (end - start) / self.lengths[:, None]
        dofs = self.nodes.shape[0] * dimension
        # ``strain[e]``: the axial strain of member e, as a row on the dofs.
        self.strain = np.zeros((len(self.members), dofs))
        for e, (i, j) in enumerate(self.members):
            self.strain[e, i * dimension : (i + 1) * dimension] = -cosines[e]
            self.strain[e, j * dimension : (j + 1) * dimension] = cosines[e]
        self.strain /= self.lengths[:, None]
        # The stiffness of each group at an area of 1.
        self.unit = np.zeros((self.size, dofs, dofs))
        for e, group in enumerate(self.groups):
            self.unit[group] += (
                YOUNG * self.lengths[e] * np.outer(self.strain[e], self.strain[e])
            )
        self.group_length = np.bincount(self.groups, self.lengths, self.size)
        limited = self.limited if self.limited is not None else ~self.fixed
        self.watched = np.flatnonzero(np.asarray(limited).ravel() & ~self.fixed.ravel())
        self.force = [np.asarray(load, dtype=float).ravel() for load in self.loads]

    def weight(self, areas: Array) -> float:
        """The weight of the truss for the areas of its groups."""
        return float(DENSITY * self.group_length @ areas)

    def analyse(self, areas: Array) -> tuple[list[Array], list[Array]]:
        """The displacements and the member stresses of each load case."""
        stiffness = np.tensordot(areas, self.unit, axes=1)
        free = self.free
        displacements = []
        stresses = []
        for force in self.force:
            u = np.zeros(force.size)
            u[free] = np.linalg.solve(stiffness[np.ix_(free, free)], force[free])
            displacements.append(u)
            stresses.append(YOUNG * self.strain @ u)
        return displacements, stresses

    def constraints(self, areas: Array) -> tuple[Array, Array]:
        """The constraints, each ``value / limit - 1 <= 0``, and their Jacobian.

        Per load case: the tension and the compression of each member, the
        displacement up and down of each watched coordinate. The Jacobian by
        the direct method: ``du/dA_g = -K⁻¹ K_g u``.
        """
        self.evaluations += 1
        stiffness = np.tensordot(areas, self.unit, axes=1)
        free = self.free
        kff = stiffness[np.ix_(free, free)]
        compression = self.stress_limits[self.groups, 0]
        tension = self.stress_limits[self.groups, 1]
        values = []
        rows = []
        for force in self.force:
            u = np.zeros(force.size)
            u[free] = np.linalg.solve(kff, force[free])
            # Columns g: K_g u restricted to the free dofs, then solved for.
            rhs = np.einsum("gij,j->ig", self.unit[:, free, :], u)
            du = np.zeros((force.size, self.size))
            du[free] = -np.linalg.solve(kff, rhs)
            stress = YOUNG * self.strain @ u
            d_stress = YOUNG * self.strain @ du
            values += [
                stress / tension - 1,
                -stress / compression - 1,
                u[self.watched] / self.displacement_limit - 1,
                -u[self.watched] / self.displacement_limit - 1,
            ]
            rows += [
                d_stress / tension[:, None],
                -d_stress / compression[:, None],
                du[self.watched] / self.displacement_limit,
                -du[self.watched] / self.displacement_limit,
            ]
        return np.concatenate(values), np.vstack(rows)

    def problem(self, start: float = 0.5) -> DenseProblem:
        """The sizing problem in the areas normalized to [0, 1].

        Args:
            start: The starting areas, as a share of the range.
        """
        scale = self.upper - self.lower

        def areas(y: Array) -> Array:
            return self.lower + scale * np.asarray(y, dtype=float)

        weights: Array = np.asarray(DENSITY * self.group_length * scale)

        return DenseProblem(
            x0=np.full(self.size, start),
            lower=np.zeros(self.size),
            upper=np.ones(self.size),
            objective=lambda y: self.weight(areas(y)),
            objective_gradient=lambda y: weights,
            constraints=lambda y: self.constraints(areas(y))[0],
            constraint_jacobian=lambda y: self.constraints(areas(y))[1] * scale,
        )

    def areas(self, y: Array) -> Array:
        """The areas of the groups for the normalized variables of ``problem``."""
        return self.lower + (self.upper - self.lower) * np.asarray(y, dtype=float)

    def worst(self, areas: Array) -> float:
        """The largest constraint at some areas: at most 0 if they are feasible."""
        return float(self.constraints(areas)[0].max())


def ten_bar() -> Truss:
    """The 10-bar cantilever truss (Schmit and Farshi): two bays of 360 in.

    A load of 100 kips down at each of the two nodes of the free end; stresses
    within ±25 ksi, displacements within 2 in, areas at least 0.1 in². The best
    known weight is 5060.85 lb (Sedaghati). Another local optimum, of 5076.85 lb
    (Schmit and Miura), attracts many runs.
    """
    nodes = [(720, 360), (720, 0), (360, 360), (360, 0), (0, 360), (0, 0)]
    members = [
        (4, 2),
        (2, 0),
        (5, 3),
        (3, 1),
        (2, 3),
        (0, 1),
        (4, 3),
        (5, 2),
        (2, 1),
        (3, 0),
    ]
    fixed = np.zeros((6, 2), dtype=bool)
    fixed[[4, 5]] = True
    load = np.zeros((6, 2))
    load[[1, 3], 1] = -100.0
    truss = Truss(
        nodes=np.array(nodes, dtype=float),
        members=np.array(members),
        groups=np.arange(10),
        fixed=fixed,
        loads=[load],
        stress_limits=np.full((10, 2), 25.0),
        displacement_limit=2.0,
        lower=0.1,
        upper=50.0,
        known=(
            5060.85,
            "Sedaghati; Schmit and Miura 5076.85; Kaveh and Rahami 5061.90",
        ),
    )
    truss.published = np.array(
        [30.5218, 0.1, 23.1999, 15.2229, 0.1, 0.5514, 7.4572, 21.0364, 21.5284, 0.1]
    )
    return truss


def twenty_five_bar() -> Truss:
    """The 25-bar space tower (Schmit and Farshi), two load cases.

    Eight groups of members; stress limits per group (Table 9 of the papers),
    displacements of every node within 0.35 in, areas at least 0.01 in². The
    best known weight is 545.16 lb (Lamberti).
    """
    nodes = [
        (-37.5, 0, 200), (37.5, 0, 200),
        (-37.5, 37.5, 100), (37.5, 37.5, 100), (37.5, -37.5, 100), (-37.5, -37.5, 100),
        (-100, 100, 0), (100, 100, 0), (100, -100, 0), (-100, -100, 0),
    ]  # fmt: skip
    members = [
        (1, 2), (1, 4), (2, 3), (1, 5), (2, 6), (2, 4), (2, 5), (1, 3), (1, 6),
        (3, 6), (4, 5), (3, 4), (5, 6), (3, 10), (6, 7), (4, 9), (5, 8), (4, 7),
        (3, 8), (5, 10), (6, 9), (6, 10), (3, 7), (4, 8), (5, 9),
    ]  # fmt: skip
    sizes = [1, 4, 4, 2, 2, 4, 4, 4]
    groups = np.repeat(np.arange(8), sizes)
    fixed = np.zeros((10, 3), dtype=bool)
    fixed[6:] = True
    first, second = np.zeros((10, 3)), np.zeros((10, 3))
    first[0], first[1] = (0, 20, -5), (0, -20, -5)
    second[0], second[1] = (1, 10, -5), (0, 10, -5)
    second[2], second[5] = (0.5, 0, 0), (0.5, 0, 0)
    compression = [35.092, 11.590, 17.305, 35.092, 35.092, 6.759, 6.959, 11.082]
    truss = Truss(
        nodes=np.array(nodes, dtype=float),
        members=np.array(members) - 1,
        groups=groups,
        fixed=fixed,
        loads=[first, second],
        stress_limits=np.column_stack([compression, np.full(8, 40.0)]),
        displacement_limit=0.35,
        lower=0.01,
        upper=5.0,
        known=(545.16, "Lamberti; Schmit and Miura 545.17; Farshi and Ziazi 545.37"),
    )
    truss.published = np.array(
        [0.01, 1.9870, 2.9935, 0.01, 0.01, 0.6840, 1.6769, 2.6621]
    )
    return truss


def seventy_two_bar() -> Truss:
    """The 72-bar space truss (Schmit and Farshi).

    Four stories of 60 in, on a base of 120 in.

    Sixteen groups (four per story, the stories numbered from the top: the
    columns, the diagonals of the faces, the horizontals, the diagonals of the
    plan); two load cases; stresses within
    ±25 ksi, the displacements of the top nodes in x and y within 0.25 in, areas
    at least 0.1 in². The best known weight is 379.62 lb.
    """
    floor = 60.0
    square = [(0, 0), (120, 0), (120, 120), (0, 120)]
    nodes = [(x, y, floor * level) for level in range(5) for x, y in square]
    members: list[tuple[int, int]] = []
    groups: list[int] = []
    # The stories are numbered from the top, as the groups of the papers: the
    # first group is the lightest, its columns carry the least.
    for story in range(4):
        low, high = 4 * (3 - story), 4 * (4 - story)
        columns = [(low + k, high + k) for k in range(4)]
        faces = []
        for k in range(4):
            a, b = low + k, low + (k + 1) % 4
            c, d = high + k, high + (k + 1) % 4
            faces += [(a, d), (b, c)]
        horizontals = [(high + k, high + (k + 1) % 4) for k in range(4)]
        plan = [(high, high + 2), (high + 1, high + 3)]
        for offset, part in enumerate((columns, faces, horizontals, plan)):
            members += part
            groups += [4 * story + offset] * len(part)
    fixed = np.zeros((20, 3), dtype=bool)
    fixed[:4] = True
    first, second = np.zeros((20, 3)), np.zeros((20, 3))
    first[16] = (5, 5, -5)
    second[16:, 2] = -5.0
    limited = np.zeros((20, 3), dtype=bool)
    limited[16:, :2] = True
    truss = Truss(
        nodes=np.array(nodes, dtype=float),
        members=np.array(members),
        groups=np.array(groups),
        fixed=fixed,
        loads=[first, second],
        stress_limits=np.full((16, 2), 25.0),
        displacement_limit=0.25,
        limited=limited,
        lower=0.1,
        upper=5.0,
        known=(379.62, "Sedaghati; Arora and Haug; Chao et al. 379.62"),
    )
    truss.published = np.array(
        [0.1565, 0.5456, 0.4104, 0.5697, 0.5237, 0.5171, 0.1, 0.1,
         1.2684, 0.5117, 0.1, 0.1, 1.8862, 0.5123, 0.1, 0.1]
    )  # fmt: skip
    return truss
