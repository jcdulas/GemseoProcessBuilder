"""The rows and directional derivatives a discipline gives on request (spec § 6).

GEMSEO differentiates whole outputs only. A discipline computing a large
constraint can offer more:

- ``compute_jacobian_rows(output_name, rows, input_data)``: the gradients of some
  components of an output, by input name, each of shape
  ``(len(rows), input size)``, dense or sparse (``RowJacobian``);
- ``compute_directional_derivatives(output_name, directions, input_data)``: the
  products of the Jacobian of an output with a batch of directions given by
  input name, each of shape ``(input size, k)``, of shape ``(output size, k)``
  (``TangentJacobian``);
- ``compute_vector_jacobian_products(weights, input_data, input_names)``: the
  products ``W_o @ dO/dI`` of blocks of weights given by output name, each of
  shape ``(k, output size)`` with the same ``k`` rows, summed over the outputs,
  by input name, each of shape ``(k, input size)`` (``AdjointJacobian``).

The plugin finds the discipline computing each constraint among the disciplines
of the formulation. Its inputs are design variables, or outputs of other
disciplines run before it without coupling: the rows are chained through them
by **reverse accumulation** (``Chaining``). At a point, the rows asked for of
every constraint given row by row are gathered; their blocks by the inputs
computed upstream become weights on the outputs of the disciplines computing
them, visited once, in reverse dependency order, over the union of the chains.
A discipline offering ``AdjointJacobian`` turns its weights into weights of its
own inputs by its products, its Jacobian never formed; another one is
linearized once per point and its products formed from its Jacobian.
Directional derivatives are chained forward the same way, through
``TangentJacobian``. A discipline coupled with others (in an MDA) is refused
(open point 5).

GEMSEO 6 gives the disciplines of a function through a private attribute of its
adapter only; if it changes, the constraints are differentiated by GEMSEO in
full, as without these protocols.
"""

from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Protocol
from typing import runtime_checkable

import numpy as np
from gemseo.algos.optimization_problem import OptimizationProblem
from gemseo.core.chains.chain import MDOChain
from gemseo.core.discipline import Discipline
from gemseo.core.mdo_functions.function_from_discipline import FunctionFromDiscipline
from gemseo.core.mdo_functions.mdo_function import MDOFunction
from gemseo.mda.base_mda import BaseMDA
from numpy.typing import NDArray
from scipy import sparse

from gemseo_lso.core.arrays import Array
from gemseo_lso.core.arrays import Indices
from gemseo_lso.core.arrays import Rows


@runtime_checkable
class RowJacobian(Protocol):
    """A discipline giving some rows of the Jacobian of an output."""

    def compute_jacobian_rows(
        self,
        output_name: str,
        rows: NDArray[np.intp],
        input_data: Mapping[str, NDArray[Any]],
    ) -> Mapping[str, Any]:
        """The gradients of some components of an output, by input name."""


@runtime_checkable
class TangentJacobian(Protocol):
    """A discipline giving directional derivatives of an output."""

    def compute_directional_derivatives(
        self,
        output_name: str,
        directions: Mapping[str, NDArray[np.float64]],
        input_data: Mapping[str, NDArray[Any]],
    ) -> NDArray[np.float64]:
        """The products of the Jacobian of an output with directions."""


@runtime_checkable
class AdjointJacobian(Protocol):
    """A discipline giving vector-Jacobian products of its outputs.

    In a solver, the products of ``k`` rows of weights cost ``k`` adjoint
    solves, where the Jacobian of its outputs costs one solve per input or per
    output component.
    """

    def compute_vector_jacobian_products(
        self,
        weights: Mapping[str, Any],
        input_data: Mapping[str, NDArray[Any]],
        input_names: Sequence[str],
    ) -> Mapping[str, Any]:
        """The products of blocks of weights with the Jacobian of the outputs.

        Args:
            weights: By output name, ``(k, output size)``, dense or sparse; the
                same ``k`` rows for every output.
            input_data: The inputs of the discipline.
            input_names: The inputs that lead to the design variables: the
                products are asked for these only.

        Returns:
            By input name, ``(k, input size)``, dense or sparse: the sum over the
            outputs of ``W_o @ dO/dI``.
        """


class CoupledError(ValueError):
    """A constraint computed by a discipline coupled with others."""


def _offers_rows(discipline: Any) -> bool:
    return callable(getattr(discipline, "compute_jacobian_rows", None))


def _offers_products(discipline: Any) -> bool:
    return callable(getattr(discipline, "compute_vector_jacobian_products", None))


def _offers_tangents(discipline: Any) -> bool:
    return callable(getattr(discipline, "compute_directional_derivatives", None))


def _offers_any(discipline: Any) -> bool:
    return (
        _offers_rows(discipline)
        or _offers_products(discipline)
        or _offers_tangents(discipline)
    )


def top_disciplines(problem: OptimizationProblem) -> list[Discipline]:
    """The disciplines the functions of a problem are computed by.

    Those of the ``FunctionFromDiscipline`` among the functions (and their
    originals); empty when there is none, or when GEMSEO no longer exposes them.
    """
    found: dict[int, Discipline] = {}
    functions: list[MDOFunction] = [problem.objective, *problem.constraints]
    for function in functions:
        current: MDOFunction | None = function
        while current is not None:
            if isinstance(current, FunctionFromDiscipline):
                adapter = current.discipline_adapter
                discipline = getattr(adapter, "_DisciplineAdapter__discipline", None)
                if isinstance(discipline, Discipline):
                    found[id(discipline)] = discipline
            original = getattr(current, "original", None)
            current = original if original is not current else None
    return list(found.values())


def hierarchy(disciplines: Iterable[Discipline]) -> list[Discipline]:
    """The disciplines, the chains and MDAs containing them, and themselves."""
    result: list[Discipline] = []

    def visit(discipline: Discipline) -> None:
        if any(item is discipline for item in result):
            return
        result.append(discipline)
        for child in getattr(discipline, "disciplines", None) or ():
            visit(child)

    for discipline in disciplines:
        visit(discipline)
    return result


def leaves(disciplines: Iterable[Discipline]) -> tuple[list[Discipline], set[int]]:
    """The disciplines inside chains and MDAs, and those coupled in an MDA.

    A discipline offering one of the protocols is a leaf, even when it holds
    other disciplines.
    """
    result: list[Discipline] = []
    coupled: set[int] = set()

    def visit(discipline: Discipline, in_mda: bool) -> None:
        inner = getattr(discipline, "disciplines", None)
        if isinstance(discipline, (MDOChain, BaseMDA)) or (
            inner and not _offers_any(discipline)
        ):
            mda = isinstance(discipline, BaseMDA) and len(inner or ()) > 1
            for child in inner or ():
                visit(child, in_mda or mda)
            return
        if all(item is not discipline for item in result):
            result.append(discipline)
        if in_mda:
            coupled.add(id(discipline))

    for discipline in disciplines:
        visit(discipline, False)
    return result, coupled


@dataclass
class Source:
    """How a constraint is differentiated by the discipline computing it."""

    discipline: Discipline
    output_name: str
    sign: float
    """-1 for a constraint ``g >= value`` (GEMSEO negates it)."""

    upstream: list[Discipline]
    """The disciplines computing its inputs that are not design variables,
    producers first."""

    design_inputs: list[str]
    """Its inputs that are design variables."""

    upstream_inputs: list[str]
    """Its inputs computed upstream."""

    @property
    def gives_rows(self) -> bool:
        """Whether its rows come from its discipline (row mode)."""
        discipline = self.discipline
        return _offers_rows(discipline) or _offers_products(discipline)

    @property
    def gives_directions(self) -> bool:
        """Whether its directional derivatives come from its discipline."""
        return _offers_tangents(self.discipline)


def sign_of(function: MDOFunction) -> float:
    """-1 when GEMSEO negated the output: a constraint ``g >= value``."""
    return -1.0 if " >= " in (function.special_repr or "") else 1.0


def find_sources(
    problem: OptimizationProblem, functions: list[MDOFunction], variables: list[str]
) -> list[Source | None]:
    """For each constraint, how its discipline can differentiate it, if it can.

    Raises:
        CoupledError: When a discipline offering rows or directional derivatives
            is coupled with others.
    """
    disciplines, coupled = leaves(top_disciplines(problem))
    producers: dict[str, Discipline] = {}
    for discipline in disciplines:
        for name in discipline.io.output_grammar:
            producers.setdefault(name, discipline)
    sources: list[Source | None] = []
    for function in functions:
        original = getattr(function, "original", function) or function
        names = list(original.output_names or function.output_names or ())
        discipline = producers.get(names[0]) if len(names) == 1 else None
        if discipline is None or not _offers_any(discipline):
            sources.append(None)
            continue
        if id(discipline) in coupled:
            name = producers[names[0]].name
            msg = (
                f"The discipline {name} computing {names[0]} is coupled with "
                "others: its rows cannot be chained through the coupling yet "
                "(open point 5); run it without an MDA, or without the row mode."
            )
            raise CoupledError(msg)
        sources.append(
            _source(discipline, names[0], original, variables, producers, coupled)
        )
    return sources


def _source(
    discipline: Discipline,
    output_name: str,
    function: MDOFunction,
    variables: list[str],
    producers: Mapping[str, Discipline],
    coupled: set[int],
) -> Source:
    """The source of a constraint, with the disciplines upstream in order."""
    inputs = list(discipline.io.input_grammar)
    design_inputs = [name for name in inputs if name in variables]
    upstream_inputs = [
        name for name in inputs if name not in variables and name in producers
    ]
    order: list[Discipline] = []
    visiting: set[int] = {id(discipline)}

    def visit(name: str) -> None:
        producer = producers.get(name)
        if producer is None or name in variables or any(p is producer for p in order):
            return
        if id(producer) in visiting or id(producer) in coupled:
            msg = (
                f"{output_name} depends on {name}, computed by {producer.name} in a "
                "coupling: its rows cannot be chained through it yet (open point 5)."
            )
            raise CoupledError(msg)
        visiting.add(id(producer))
        for item in producer.io.input_grammar:
            visit(item)
        visiting.discard(id(producer))
        order.append(producer)

    for name in upstream_inputs:
        visit(name)
    return Source(
        discipline=discipline,
        output_name=output_name,
        sign=sign_of(function),
        upstream=order,
        design_inputs=design_inputs,
        upstream_inputs=upstream_inputs,
    )


@dataclass
class _Pending:
    """Weights waiting for the discipline computing a variable: rows and blocks."""

    rows: list[Indices] = field(default_factory=list)
    """The rows of each block among all the rows asked for at the point."""

    blocks: list[Rows] = field(default_factory=list)


class Chaining:
    """The rows and directions of constraints chained through upstream disciplines.

    Args:
        sources: The sources of the constraints given row by row or by
            directional derivatives.
        variables: The names of the design variables.
        offsets: Where each design variable is in the design vector.
        scale: The ranges of the variables (normalized space), or ones.
        batch_size: The rows per call of ``compute_vector_jacobian_products``
            (0: all at once).
    """

    def __init__(
        self,
        sources: Sequence[Source],
        variables: list[str],
        offsets: Mapping[str, slice],
        scale: Array,
        batch_size: int = 0,
    ) -> None:
        self.variables = variables
        self.offsets = offsets
        self.scale = scale
        self.batch_size = batch_size
        order: list[Discipline] = []
        for source in sources:
            for discipline in source.upstream:
                if all(item is not discipline for item in order):
                    order.append(discipline)
        self.order = _sorted(order)
        """The upstream disciplines of every constraint, producers first."""
        produced = {
            name: discipline
            for discipline in self.order
            for name in discipline.io.output_grammar
        }
        self.leads: dict[int, list[str]] = {}
        """By discipline, its inputs leading to the design variables."""
        for discipline in self.order:
            self.leads[id(discipline)] = [
                name
                for name in discipline.io.input_grammar
                if name in variables
                or (name in produced and self.leads.get(id(produced[name])))
            ]
        self.needed: dict[int, list[str]] = {id(d): [] for d in self.order}
        """By discipline, its outputs read by a discipline downstream."""
        readers = [*self.order, *(source.discipline for source in sources)]
        for reader in readers:
            for name in reader.io.input_grammar:
                producer = produced.get(name)
                if (
                    producer is not None
                    and producer is not reader
                    and self.leads[id(producer)]
                    and name not in self.needed[id(producer)]
                ):
                    self.needed[id(producer)].append(name)
        self._point: bytes | None = None
        self._values: dict[str, Any] = {}
        self._jacobians: dict[int, Mapping[str, Mapping[str, Any]]] = {}
        self.calls = 0
        """Calls of ``compute_vector_jacobian_products`` on the intermediates."""

    # Values -----------------------------------------------------------------

    def values(self, design: Mapping[str, NDArray[Any]], key: bytes) -> dict[str, Any]:
        """The design variables and the outputs of the upstream disciplines.

        The disciplines are executed once per point, in order; GEMSEO's caches
        of the disciplines serve the executions of the evaluation of the point.
        """
        if key != self._point:
            self._point = key
            self._jacobians = {}
            values: dict[str, Any] = dict(design)
            for discipline in self.order:
                outputs = discipline.execute(self.inputs(discipline, values))
                values.update(
                    {name: outputs[name] for name in discipline.io.output_grammar}
                )
            self._values = values
        return self._values

    @staticmethod
    def inputs(discipline: Discipline, values: Mapping[str, Any]) -> dict[str, Any]:
        """The inputs of a discipline: the values known, else its defaults."""
        data = dict(discipline.io.input_grammar.defaults)
        names = discipline.io.input_grammar
        data.update({name: values[name] for name in names if name in values})
        return data

    def _jacobian(
        self, discipline: Discipline, values: Mapping[str, Any]
    ) -> Mapping[str, Mapping[str, Any]]:
        """The Jacobian of a discipline without the products, once per point."""
        if id(discipline) not in self._jacobians:
            discipline.add_differentiated_inputs(self.leads[id(discipline)])
            discipline.add_differentiated_outputs(self.needed[id(discipline)])
            jacobian = discipline.linearize(self.inputs(discipline, values))
            # A copy: GEMSEO may linearize the discipline again at this point.
            self._jacobians[id(discipline)] = {
                output: dict(blocks) for output, blocks in jacobian.items()
            }
        return self._jacobians[id(discipline)]

    # Rows by reverse accumulation --------------------------------------------

    def rows(
        self,
        requests: Sequence[tuple[Source, Indices]],
        design: Mapping[str, NDArray[Any]],
        key: bytes,
    ) -> list[Rows]:
        """The rows asked for of several constraints, in the normalized space.

        Args:
            requests: The constraints and their rows, local to each.
            design: The design variables, in physical units.
            key: The point.

        Returns:
            For each request, its rows ``(len(rows), design size)``, signed.
        """
        values = self.values(design, key)
        starts = np.cumsum([0, *(len(rows) for _, rows in requests)])
        total = int(starts[-1])
        found: dict[str, _Pending] = {}
        pending: dict[str, _Pending] = {}
        for (source, local), start in zip(requests, starts[:-1], strict=False):
            positions = np.arange(start, start + len(local))
            given = self._constraint_rows(source, local, values)
            for name, block in given.items():
                if name in self.offsets:
                    _add(found, name, positions, block)
                elif name in source.upstream_inputs:
                    _add(pending, name, positions, block)
        for discipline in reversed(self.order):
            outputs = [name for name in self.needed[id(discipline)] if name in pending]
            if not outputs:
                continue
            weights = {name: pending.pop(name) for name in outputs}
            for positions, products in self._products(discipline, weights, values):
                for name, block in products.items():
                    if name in self.offsets:
                        _add(found, name, positions, block)
                    elif name in self.leads[id(discipline)]:
                        _add(pending, name, positions, block)
        return self._assembled(found, requests, starts, total)

    def _constraint_rows(
        self, source: Source, local: Indices, values: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """The rows of a constraint by the inputs of its discipline."""
        discipline: Any = source.discipline
        data = self.inputs(discipline, values)
        if _offers_rows(discipline):
            return discipline.compute_jacobian_rows(  # type: ignore[no-any-return]
                source.output_name, local, data
            )
        # The size of the output: GEMSEO's cache serves this execution.
        size = int(np.size(discipline.execute(data)[source.output_name]))
        unit = sparse.csr_matrix(
            (np.ones(len(local)), (np.arange(len(local)), local)),
            shape=(len(local), size),
        )
        names = [*source.design_inputs, *source.upstream_inputs]
        return discipline.compute_vector_jacobian_products(  # type: ignore[no-any-return]
            {source.output_name: unit}, data, names
        )

    def _products(
        self,
        discipline: Discipline,
        weights: Mapping[str, "_Pending"],
        values: Mapping[str, Any],
    ) -> list[tuple[Indices, Mapping[str, Any]]]:
        """The products of the weights of the outputs of an upstream discipline.

        The weights of several constraints are stacked on the rows they touch;
        the discipline offering the products receives them by batches of
        ``batch_size`` rows; another one is linearized once per point.
        """
        positions = np.unique(
            np.concatenate([np.concatenate(item.rows) for item in weights.values()])
        )
        stacked = {
            name: _stacked(item, positions, int(np.size(values[name])))
            for name, item in weights.items()
        }
        inputs = self.leads[id(discipline)]
        if _offers_products(discipline):
            batch = self.batch_size or max(positions.size, 1)
            results = []
            caller: Any = discipline
            data = self.inputs(discipline, values)
            for start in range(0, positions.size, batch):
                batch_rows = slice(start, start + batch)
                self.calls += 1
                given = caller.compute_vector_jacobian_products(
                    {name: block[batch_rows] for name, block in stacked.items()},
                    data,
                    inputs,
                )
                results.append((positions[batch_rows], given))
            return results
        jacobian = self._jacobian(discipline, values)
        products: dict[str, Any] = {}
        for name in inputs:
            for output, block in stacked.items():
                derivative = jacobian.get(output, {}).get(name)
                if derivative is None:
                    continue
                product = _times(block, derivative)
                products[name] = (
                    product if name not in products else products[name] + product
                )
        return [(positions, products)]

    def _assembled(
        self,
        found: Mapping[str, "_Pending"],
        requests: Sequence[tuple[Source, Indices]],
        starts: NDArray[np.intp],
        total: int,
    ) -> list[Rows]:
        """The rows by design variable placed in the design vector, scaled, signed."""
        size = int(self.scale.size)
        dense: Array | None = None
        rows: list[NDArray[np.intp]] = []
        columns: list[NDArray[np.intp]] = []
        data: list[Array] = []
        for name, item in found.items():
            offset = self.offsets[name].start
            for positions, block in zip(item.rows, item.blocks, strict=True):
                if sparse.issparse(block):
                    coo = sparse.coo_matrix(block)
                    rows.append(positions[coo.row])
                    columns.append(coo.col + offset)
                    data.append(np.asarray(coo.data, dtype=float))
                else:
                    if dense is None:
                        dense = np.zeros((total, size))
                    values = np.real(np.asarray(block, dtype=float))
                    dense[positions, offset : offset + values.shape[1]] += values
        entries = (
            np.concatenate(data) if data else np.zeros(0),
            np.concatenate(rows) if rows else np.zeros(0, dtype=np.intp),
            np.concatenate(columns) if columns else np.zeros(0, dtype=np.intp),
        )
        assembled: Rows
        if dense is not None:
            # The sparse blocks added in place: no second dense copy.
            np.add.at(dense, (entries[1], entries[2]), entries[0])
            dense *= self.scale[None, :]
            assembled = dense
        else:
            assembled = sparse.csr_matrix(
                (entries[0], (entries[1], entries[2])), shape=(total, size)
            )
            assembled = sparse.csr_matrix(assembled.multiply(self.scale[None, :]))
        return [
            assembled[start:stop] * source.sign
            for (source, _), start, stop in zip(
                requests, starts[:-1], starts[1:], strict=True
            )
        ]

    # Directions by forward accumulation --------------------------------------

    def directions(
        self,
        sources: Sequence[Source],
        directions: sparse.csc_matrix,
        design: Mapping[str, NDArray[Any]],
        key: bytes,
    ) -> list[NDArray[np.float64]]:
        """The products of the Jacobians of constraints with normalized directions.

        The directions are propagated forward through the upstream disciplines,
        by their directional derivatives when they offer them, else by their
        Jacobians (once per point).
        """
        values = self.values(design, key)
        physical = sparse.csr_matrix(directions.multiply(self.scale[:, None]))
        tangents: dict[str, Any] = {
            name: physical[self.offsets[name]].toarray() for name in self.variables
        }
        for discipline in self.order:
            inputs = self.leads[id(discipline)]
            outputs = self.needed[id(discipline)]
            if not outputs:
                continue
            given = {name: tangents[name] for name in inputs if name in tangents}
            if _offers_tangents(discipline):
                caller: Any = discipline
                data = self.inputs(discipline, values)
                for name in outputs:
                    tangents[name] = np.asarray(
                        caller.compute_directional_derivatives(name, given, data)
                    )
                continue
            jacobian = self._jacobian(discipline, values)
            for name in outputs:
                product: Any = 0.0
                for item, direction in given.items():
                    part = jacobian.get(name, {}).get(item)
                    if part is not None:
                        product = product + _times(part, direction)
                tangents[name] = np.asarray(product)
        results = []
        for source in sources:
            caller = source.discipline
            data = self.inputs(caller, values)
            given = {name: tangents[name] for name in source.design_inputs}
            given.update({name: tangents[name] for name in source.upstream_inputs})
            products = caller.compute_directional_derivatives(
                source.output_name, given, data
            )
            results.append(np.asarray(products, dtype=float) * source.sign)
        return results


def _add(target: dict[str, _Pending], name: str, rows: Indices, block: Any) -> None:
    item = target.setdefault(name, _Pending())
    item.rows.append(rows)
    item.blocks.append(block if sparse.issparse(block) else np.asarray(block))


def _stacked(item: _Pending, positions: Indices, size: int) -> Rows:
    """The blocks of weights summed on the rows they touch, sparse if all are."""
    where = [np.searchsorted(positions, rows) for rows in item.rows]
    if all(sparse.issparse(block) for block in item.blocks):
        coo = [sparse.coo_matrix(block) for block in item.blocks]
        rows = [w[block.row] for w, block in zip(where, coo, strict=True)]
        return sparse.csr_matrix(
            (
                np.concatenate([block.data for block in coo]),
                (np.concatenate(rows), np.concatenate([block.col for block in coo])),
            ),
            shape=(positions.size, size),
        )
    stacked = np.zeros((positions.size, size))
    for places, block in zip(where, item.blocks, strict=True):
        stacked[places] += block.toarray() if sparse.issparse(block) else block
    return stacked


def _times(left: Any, right: Any) -> Any:
    """A product of dense or sparse matrices, sparse when both are."""
    if sparse.issparse(left) and sparse.issparse(right):
        return sparse.csr_matrix(left @ right)
    if sparse.issparse(left) or sparse.issparse(right):
        return np.asarray(left @ right)
    return np.asarray(left) @ np.asarray(right)


def _sorted(disciplines: list[Discipline]) -> list[Discipline]:
    """The disciplines in dependency order: the producers of a discipline first."""
    produced = {
        name: discipline
        for discipline in disciplines
        for name in discipline.io.output_grammar
    }
    order: list[Discipline] = []

    def visit(discipline: Discipline) -> None:
        if any(item is discipline for item in order):
            return
        for name in discipline.io.input_grammar:
            producer = produced.get(name)
            if producer is not None and producer is not discipline:
                visit(producer)
        order.append(discipline)

    for discipline in disciplines:
        visit(discipline)
    return order
