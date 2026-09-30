"""A GEMSEO ``OptimizationProblem`` seen through the protocol of the core (§ 5, § 6).

- **Values** through GEMSEO's functions: its database and its listeners (the
  Claude copilot among them) see every evaluation, and its stopping criteria
  apply.
- **Gradients** of the objective and of the equality constraints: GEMSEO's.
- **Rows** of the inequality constraints: from the discipline computing a
  constraint when it offers them (``RowJacobian``), else from the whole
  Jacobian GEMSEO computes, once per point.
- **Directional derivatives** (``hybrid``): from the disciplines offering them
  (``TangentJacobian``) when all the inequality constraints have one; else
  ``None``, and the optimizer uses finite differences.
- **Normalization**: GEMSEO normalizes the design space and the functions; the
  rows and directions of the disciplines, in physical units, are scaled by the
  ranges.
- **Signs**: GEMSEO's ``g <= 0`` is the optimizer's; a constraint ``g >= value``
  is negated by GEMSEO, and so are its rows.
"""

import logging
from collections.abc import Callable
from typing import Any

import numpy as np
from gemseo.algos.design_space_utils import get_value_and_bounds
from gemseo.algos.optimization_problem import OptimizationProblem
from gemseo.core.mdo_functions.mdo_function import MDOFunction
from numpy.typing import NDArray
from scipy import sparse

from gemseo_lso.core.arrays import Array
from gemseo_lso.core.arrays import Indices
from gemseo_lso.core.arrays import Rows
from gemseo_lso.core.arrays import stack_rows
from gemseo_lso.core.optimizer import ProblemError
from gemseo_lso.gemseo.settings import BaseLSOSettings
from gemseo_lso.gemseo.sources import CoupledError
from gemseo_lso.gemseo.sources import RowJacobian
from gemseo_lso.gemseo.sources import Source
from gemseo_lso.gemseo.sources import TangentJacobian
from gemseo_lso.gemseo.sources import directional_of
from gemseo_lso.gemseo.sources import find_sources
from gemseo_lso.gemseo.sources import hierarchy
from gemseo_lso.gemseo.sources import rows_of
from gemseo_lso.gemseo.sources import top_disciplines

LOGGER = logging.getLogger(__name__)


class GemseoProblem:
    """The protocol of the core on a GEMSEO optimization problem.

    Args:
        problem: The problem, its functions preprocessed by GEMSEO.
        settings: The settings of the algorithm.
    """

    def __init__(self, problem: OptimizationProblem, settings: BaseLSOSettings) -> None:
        self.problem = problem
        self.settings = settings
        design_space = problem.design_space
        self._normalize = settings.normalize_design_space
        x0, lower, upper = get_value_and_bounds(design_space, self._normalize)
        if not (np.all(np.isfinite(lower)) and np.all(np.isfinite(upper))):
            msg = "LSO algorithms need finite bounds on every design variable."
            raise ProblemError(msg)
        self._x0 = np.asarray(np.real(x0), dtype=float)
        self._lower = np.asarray(lower, dtype=float)
        self._upper = np.asarray(upper, dtype=float)
        self.variables: list[str] = list(design_space.variable_names)
        sizes = design_space.variable_sizes
        self.offsets: dict[str, slice] = {}
        start = 0
        for name in self.variables:
            self.offsets[name] = slice(start, start + sizes[name])
            start += sizes[name]
        physical = design_space.get_upper_bounds() - design_space.get_lower_bounds()
        self._scale: Array = (
            np.asarray(physical, dtype=float) if self._normalize else np.ones(start)
        )
        self.inequalities: list[MDOFunction] = list(
            problem.constraints.get_inequality_constraints()
        )
        self.equalities: list[MDOFunction] = list(
            problem.constraints.get_equality_constraints()
        )
        _, constraints, _ = self._values(self._x0)
        self._blocks = self._block_offsets(self._x0)
        self.constraint_slices: dict[str, slice] = {
            function.name: slice(start, stop)
            for function, (start, stop) in zip(
                self.inequalities, self._blocks, strict=True
            )
        }
        """Where each inequality constraint is among all of them."""
        self._jacobian_at: bytes | None = None
        self._jacobians: dict[int, Rows] = {}
        self.rows_given = 0
        try:
            self.sources = find_sources(problem, self.inequalities, self.variables)
        except CoupledError as error:
            raise ProblemError(str(error)) from None
        if any(self.sources) and settings.scaling_threshold is not None:
            msg = (
                "The rows given by the disciplines cannot be scaled: "
                "scaling_threshold must be None with LSO algorithms."
            )
            raise ProblemError(msg)
        rows_mode = [
            s
            for s in self.sources
            if s is not None and isinstance(s.discipline, RowJacobian)
        ]
        if rows_mode:
            LOGGER.info(
                "%d of %d inequality constraints differentiated row by row by "
                "their disciplines.",
                len(rows_mode),
                len(self.inequalities),
            )
        self._constraint_size = constraints.size

    def detach_row_outputs(self) -> Callable[[], None]:
        """Stop GEMSEO from differentiating the outputs the optimizer gets otherwise.

        GEMSEO linearizes a discipline for all its differentiated outputs at
        once: the gradient of the objective would compute the whole Jacobian of
        the constraints of the same discipline. The outputs given row by row
        (``RowJacobian``) are removed from the differentiated outputs of their
        disciplines for the run, unless the objective or an equality constraint
        needs them.

        Returns:
            What puts them back.
        """
        needed = set(_outputs(self.problem.objective))
        for function in self.equalities:
            needed.update(_outputs(function))
        detached = {
            source.output_name
            for source in self.sources
            if source is not None
            and source.output_name not in needed
            and isinstance(source.discipline, RowJacobian)
        }
        removed: list[tuple[Any, list[str]]] = []
        # The chains and MDAs pass their differentiated outputs down.
        for discipline in hierarchy(top_disciplines(self.problem)):
            names = getattr(discipline, "_differentiated_output_names", None)
            if not names or not detached.intersection(names):
                continue
            removed.append((discipline, list(names)))
            discipline._differentiated_output_names = [
                name for name in names if name not in detached
            ]

        def restore() -> None:
            for discipline, names in reversed(removed):
                discipline._differentiated_output_names = names

        return restore

    def optimizer_point(self, x: Array) -> Array:
        """A design vector of GEMSEO in the space of the optimizer (normalized)."""
        space = self.problem.design_space
        point = space.normalize_vect(x) if self._normalize else x
        return np.asarray(np.real(point), dtype=float)

    @property
    def x0(self) -> Array:
        """The current point of the design space, normalized if asked for."""
        return self._x0

    @property
    def lower(self) -> Array:
        """The lower bounds."""
        return self._lower

    @property
    def upper(self) -> Array:
        """The upper bounds."""
        return self._upper

    def _values(self, x: Array) -> tuple[float, Array, Array]:
        objective = float(np.real(np.ravel(self.problem.objective.evaluate(x))[0]))
        return (
            objective,
            _concatenated(self.inequalities, x),
            _concatenated(self.equalities, x),
        )

    def values(self, x: Array) -> tuple[float, Array, Array]:
        """The objective, the inequality and the equality constraints."""
        return self._values(x)

    def objective_gradient(self, x: Array) -> Array:
        """GEMSEO's gradient of the objective."""
        return np.asarray(np.real(self.problem.objective.jac(x)), dtype=float).ravel()

    def equality_rows(self, x: Array) -> Array:
        """GEMSEO's Jacobian of the equality constraints."""
        if not self.equalities:
            return np.zeros((0, x.size))
        blocks = [
            _dense_jacobian(function.jac(x), x.size) for function in self.equalities
        ]
        return np.vstack(blocks)

    def constraint_rows(self, x: Array, rows: Indices) -> Rows:
        """Some rows, from the disciplines offering them, else from GEMSEO."""
        self.rows_given += len(rows)
        key = x.tobytes()
        design = self._design(x)
        parts: list[Rows] = []
        order: list[NDArray[np.intp]] = []
        for index, (start, stop) in enumerate(self._blocks):
            local = rows[(rows >= start) & (rows < stop)] - start
            if not local.size:
                continue
            order.append(np.flatnonzero((rows >= start) & (rows < stop)))
            source = self.sources[index]
            if source is not None and isinstance(source.discipline, RowJacobian):
                parts.append(
                    rows_of(
                        source,
                        local,
                        design,
                        key,
                        self.variables,
                        self.offsets,
                        self._scale,
                    )
                )
            else:
                parts.append(self._jacobian(index, x)[local])
        stacked = stack_rows(parts, x.size)
        positions = np.concatenate(order) if order else np.zeros(0, dtype=np.intp)
        if np.array_equal(positions, np.arange(positions.size)):
            return stacked
        return stacked[np.argsort(positions)]

    def sparsity(self) -> Any:
        """The pattern given by ``sparsity_pattern``, if any."""
        function = self.settings.sparsity_pattern
        if function is None:
            return None
        variables = [
            (name, self.offsets[name].stop - self.offsets[name].start)
            for name in self.variables
        ]
        constraints = [
            (_name(constraint), stop - start)
            for constraint, (start, stop) in zip(
                self.inequalities, self._blocks, strict=True
            )
        ]
        return function(variables, constraints)

    def directional_derivatives(
        self, x: Array, directions: sparse.csc_matrix
    ) -> NDArray[np.float64] | None:
        """From the disciplines, when every inequality constraint has one."""
        if not self.sources or not all(
            source is not None and isinstance(source.discipline, TangentJacobian)
            for source in self.sources
        ):
            return None
        key = x.tobytes()
        design = self._design(x)
        return np.vstack(
            [
                directional_of(
                    source,
                    directions,
                    design,
                    key,
                    self.variables,
                    self.offsets,
                    self._scale,
                )
                for source in self.sources
                if source is not None
            ]
        )

    def _design(self, x: Array) -> dict[str, NDArray[Any]]:
        """The design variables at ``x``, in physical units."""
        space = self.problem.design_space
        physical = space.unnormalize_vect(x) if self._normalize else x
        return dict(space.convert_array_to_dict(physical))

    def _jacobian(self, index: int, x: Array) -> Rows:
        """GEMSEO's Jacobian of a constraint at ``x``, computed once per point."""
        key = x.tobytes()
        if key != self._jacobian_at:
            self._jacobian_at = key
            self._jacobians = {}
        if index not in self._jacobians:
            jacobian = self.inequalities[index].jac(x)
            if sparse.issparse(jacobian):
                self._jacobians[index] = sparse.csr_matrix(jacobian)
            else:
                self._jacobians[index] = _dense_jacobian(jacobian, x.size)
        return self._jacobians[index]

    def _block_offsets(self, x: Array) -> list[tuple[int, int]]:
        """Where each inequality constraint is in the vector of all of them."""
        blocks = []
        start = 0
        for function in self.inequalities:
            size = np.atleast_1d(function.evaluate(x)).size
            blocks.append((start, start + size))
            start += size
        return blocks


def _concatenated(functions: list[MDOFunction], x: Array) -> Array:
    if not functions:
        return np.zeros(0)
    return np.concatenate(
        [
            np.atleast_1d(np.real(function.evaluate(x))).astype(float)
            for function in functions
        ]
    )


def _dense_jacobian(jacobian: Any, size: int) -> Array:
    array = jacobian.toarray() if sparse.issparse(jacobian) else np.asarray(jacobian)
    return np.real(array).reshape(-1, size).astype(float)


def _outputs(function: MDOFunction) -> list[str]:
    """The discipline outputs a function is computed from."""
    original = getattr(function, "original", function) or function
    return list(original.output_names or function.output_names or ())


def _name(function: MDOFunction) -> str:
    """The name of a constraint for the pattern function: its output, if one."""
    original = getattr(function, "original", function) or function
    names = list(original.output_names or ())
    return str(names[0] if len(names) == 1 else function.name)


__all__ = ["GemseoProblem", "Source"]
