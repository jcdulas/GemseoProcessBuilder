"""The rows and directional derivatives a discipline gives on request (spec § 6).

GEMSEO differentiates whole outputs only. A discipline computing a large
constraint can offer more:

- ``compute_jacobian_rows(output_name, rows, input_data)``: the gradients of some
  components of an output, by input name, each of shape
  ``(len(rows), input size)``, dense or sparse (``RowJacobian``);
- ``compute_directional_derivatives(output_name, directions, input_data)``: the
  products of the Jacobian of an output with a batch of directions given by
  input name, each of shape ``(input size, k)``, of shape ``(output size, k)``
  (``TangentJacobian``).

The plugin finds the discipline computing each constraint among the disciplines
of the formulation. Its inputs are design variables, or outputs of other
disciplines run before it without coupling: their Jacobians with respect to the
design variables are chained. A discipline coupled with others (in an MDA) is
refused (open point 5).

GEMSEO 6 gives the disciplines of a function through a private attribute of its
adapter only; if it changes, the constraints are differentiated by GEMSEO in
full, as without these protocols.
"""

from collections.abc import Iterable
from collections.abc import Mapping
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


class CoupledError(ValueError):
    """A constraint computed by a discipline coupled with others."""


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
    """The disciplines inside chains and MDAs, and those coupled in an MDA."""
    result: list[Discipline] = []
    coupled: set[int] = set()

    def visit(discipline: Discipline, in_mda: bool) -> None:
        inner = getattr(discipline, "disciplines", None)
        if isinstance(discipline, (MDOChain, BaseMDA)) or (
            inner and not isinstance(discipline, (RowJacobian, TangentJacobian))
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

    upstream: MDOChain | None
    """The disciplines computing its inputs that are not design variables."""

    design_inputs: list[str]
    """Its inputs that are design variables."""

    upstream_inputs: list[str]
    """Its inputs computed upstream."""

    _linearized: dict[bytes, dict[str, dict[str, Any]]] = field(
        default_factory=dict, repr=False
    )

    def input_data(self, design: Mapping[str, NDArray[Any]]) -> dict[str, NDArray[Any]]:
        """The inputs of the discipline at a point of the design space."""
        data = dict(self.discipline.io.input_grammar.defaults)
        data.update({name: design[name] for name in self.design_inputs})
        if self.upstream is not None:
            upstream = dict(self.upstream.io.input_grammar.defaults)
            upstream.update(
                {name: value for name, value in design.items() if name in upstream}
            )
            outputs = self.upstream.execute(upstream)
            data.update({name: outputs[name] for name in self.upstream_inputs})
        return data

    def upstream_jacobian(
        self, design: Mapping[str, NDArray[Any]], key: bytes, variables: list[str]
    ) -> dict[str, dict[str, Any]]:
        """The Jacobian of the upstream inputs with respect to the design."""
        if self.upstream is None:
            return {}
        if key not in self._linearized:
            chain = self.upstream
            names = [name for name in variables if name in chain.io.input_grammar]
            chain.add_differentiated_inputs(names)
            chain.add_differentiated_outputs(self.upstream_inputs)
            data = dict(chain.io.input_grammar.defaults)
            data.update({name: design[name] for name in names})
            self._linearized = {key: chain.linearize(data)}
        return self._linearized[key]


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
        if discipline is None or not isinstance(
            discipline, (RowJacobian, TangentJacobian)
        ):
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
        upstream=MDOChain(order) if order else None,
        design_inputs=design_inputs,
        upstream_inputs=upstream_inputs,
    )


def rows_of(
    source: Source,
    rows: Indices,
    design: Mapping[str, NDArray[Any]],
    key: bytes,
    variables: list[str],
    offsets: Mapping[str, slice],
    scale: Array,
) -> sparse.csr_matrix:
    """Some rows of a constraint, with respect to the (normalized) design vector."""
    discipline = source.discipline
    assert isinstance(discipline, RowJacobian)
    data = source.input_data(design)
    given = discipline.compute_jacobian_rows(source.output_name, rows, data)
    jacobian = source.upstream_jacobian(design, key, variables)
    size = int(scale.size)
    total = sparse.csr_matrix((len(rows), size))
    for name, block in given.items():
        block = sparse.csr_matrix(block)
        if name in offsets:
            total = total + _placed(block, offsets[name], size)
        for variable, part in jacobian.get(name, {}).items():
            if variable in offsets:
                total = total + _placed(
                    sparse.csr_matrix(block @ sparse.csr_matrix(part)),
                    offsets[variable],
                    size,
                )
    return sparse.csr_matrix(total.multiply(scale[None, :]) * source.sign)


def directional_of(
    source: Source,
    directions: sparse.csc_matrix,
    design: Mapping[str, NDArray[Any]],
    key: bytes,
    variables: list[str],
    offsets: Mapping[str, slice],
    scale: Array,
) -> NDArray[np.float64]:
    """The products of the Jacobian of a constraint with normalized directions."""
    discipline = source.discipline
    assert isinstance(discipline, TangentJacobian)
    physical = sparse.csr_matrix(directions.multiply(scale[:, None]))
    by_variable = {name: physical[offsets[name]].toarray() for name in variables}
    data = source.input_data(design)
    jacobian = source.upstream_jacobian(design, key, variables)
    given = {name: by_variable[name] for name in source.design_inputs}
    for name in source.upstream_inputs:
        product = 0.0
        for variable, part in jacobian.get(name, {}).items():
            if variable in by_variable:
                product = product + sparse.csr_matrix(part) @ by_variable[variable]
        given[name] = np.asarray(product)
    products = discipline.compute_directional_derivatives(
        source.output_name, given, data
    )
    return np.asarray(products, dtype=float) * source.sign


def _placed(block: sparse.csr_matrix, columns: slice, size: int) -> sparse.csr_matrix:
    """A block of columns placed at its columns of the design vector."""
    coo = block.tocoo()
    return sparse.csr_matrix(
        (coo.data, (coo.row, coo.col + columns.start)), shape=(block.shape[0], size)
    )
