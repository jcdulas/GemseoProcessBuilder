"""The derivatives of generated scripts, in the worker (SPEC § 9.3).

Two questions are answered here:

- where the derivatives of each discipline come from: computed exactly (an
  analytic discipline, a class computing its Jacobian), approximated by finite
  differences, or missing;
- whether the derivatives GEMSEO assembles are right: they are compared with
  centered finite differences, output by output and input by input. For a
  driver, the objective and the constraints are differentiated with respect to
  the design variables through the whole process (MDA and adjoint included):
  this shows the gradients go up through the couplings.
"""

import time
from collections.abc import Iterator
from typing import Any

import numpy as np

from gemseo_process_builder.workers.codegen_methods import loaded_script
from gemseo_process_builder.workers.gemseo_loader import require_gemseo
from gemseo_process_builder.workers.server import RequestContext
from gemseo_process_builder.workers.server import WorkerError

TOLERANCE = 1e-4
"""Largest error accepted, relative to the size of the derivative (and at least 1)."""

STEP = 1e-6
"""Step of the centered finite differences, relative to each value (at least 0.01)."""

MAX_VARIABLES = 40
"""Inputs and outputs checked at most: the approximation costs two runs per input."""

APPROXIMATED = {
    "finite_differences",
    "centered_differences",
    "complex_step",
    "hybrid_complex_step",
    "hybrid_finite_differences",
    "hybrid_centered_differences",
}


def _children(discipline: Any) -> list[Any]:
    """The disciplines inside a composite discipline (chain, MDA, adapter)."""
    children = list(getattr(discipline, "disciplines", []) or [])
    scenario = getattr(discipline, "scenario", None)
    if scenario is not None:
        children += list(scenario.formulation.disciplines)
    return children


def _walk(disciplines: list[Any]) -> Iterator[Any]:
    """Every discipline, with those inside the composite ones."""
    for discipline in disciplines:
        yield discipline
        yield from _walk(_children(discipline))


def origin(discipline: Any) -> str:
    """Where the derivatives of a discipline come from.

    Returns:
        ``exact``, ``approximated`` or ``missing``.
    """
    from gemseo.core.discipline import Discipline
    from gemseo.disciplines.auto_py import AutoPyDiscipline

    if str(getattr(discipline.linearization_mode, "value", "")) in APPROXIMATED:
        return "approximated"
    if getattr(discipline, "scenario", None) is not None:
        # A nested driver: the derivatives of an optimum are sensitivities.
        return "approximated"
    children = _children(discipline)
    if children:
        origins = {origin(child) for child in children}
        for worst in ("missing", "approximated"):
            if worst in origins:
                return worst
        return "exact"
    if isinstance(discipline, AutoPyDiscipline) and discipline.py_jac is None:
        return "missing"
    overridden = type(discipline)._compute_jacobian is not Discipline._compute_jacobian
    return "exact" if overridden else "missing"


def _top_disciplines(module: Any, mapping: dict[str, Any]) -> tuple[list[Any], Any]:
    """The disciplines a script builds, and its scenario if it has one."""
    if mapping.get("kind") == "scenario":
        scenario = module.build_scenario()
        return list(scenario.formulation.disciplines), scenario
    return [module.build_process()], None


def origins(source: str, mapping: dict[str, Any]) -> dict[str, str]:
    """The origin of the derivatives of each node of a script, by node id."""
    names = {name: node for node, name in mapping.get("disciplines", {}).items()}
    found: dict[str, str] = {}
    with loaded_script(source) as module:
        disciplines, _ = _top_disciplines(module, mapping)
        for discipline in _walk(disciplines):
            node = names.get(discipline.name)
            if node is not None and node not in found:
                found[node] = origin(discipline)
    return found


def _float_names(names: Any, data: dict[str, Any]) -> list[str]:
    """The names of real-valued data, in order."""
    return [
        name
        for name in names
        if name in data and np.issubdtype(np.asarray(data[name]).dtype, np.number)
    ]


def _problem(scenario: Any) -> tuple[Any, list[str], list[str], dict[str, Any]]:
    """What a driver differentiates.

    Returns:
        Its process, the design variables, the objective and constraints, and
        the values of the design variables.
    """
    from gemseo import create_mda
    from gemseo.core.chains.chain import MDOChain
    from gemseo.core.chains.parallel_chain import MDOParallelChain

    formulation = scenario.formulation
    problem = formulation.optimization_problem
    outputs = list(problem.objective.output_names)
    for constraint in problem.constraints:
        outputs += [name for name in constraint.output_names if name not in outputs]
    design_space = problem.design_space
    inputs = list(design_space.variable_names)
    tops = formulation.get_top_level_disciplines()
    if len(tops) == 1:
        process = tops[0]
    elif formulation.__class__.__name__ == "MDF":
        process = create_mda("MDAChain", list(formulation.disciplines))
    elif formulation.__class__.__name__ == "IDF":
        # The couplings are design variables: every discipline takes them as inputs.
        process = MDOParallelChain(list(tops))
    else:
        process = MDOChain(list(tops))
    if design_space.has_current_value:
        values = design_space.get_current_value(as_dict=True)
    else:
        # A DOE has no starting point: the middle of the bounds.
        values = {
            name: (
                design_space.get_lower_bound(name) + design_space.get_upper_bound(name)
            )
            / 2
            for name in inputs
        }
    return process, inputs, outputs, values


def _point(disciplines: list[Any], scenario: Any) -> None:
    """Run the process once, so that each discipline holds realistic inputs.

    Its coupled inputs are then computed by the others, not their default zeros.
    """
    if scenario is not None:
        process, _, _, values = _problem(scenario)
        process.execute({**process.default_input_data, **values})
    else:
        disciplines[0].execute()


def _nested(process: Any) -> bool:
    """Whether a process contains a nested driver."""
    return any(getattr(d, "scenario", None) is not None for d in _walk([process]))


def check(
    source: str, mapping: dict[str, Any], discipline_name: str = ""
) -> dict[str, Any]:
    """Compare the derivatives of a discipline, process or driver with differences.

    Args:
        source: The generated script.
        mapping: Its sidecar mapping.
        discipline_name: A discipline of the script to check; by default, what
            the script runs (its scenario or its process).
    """
    started = time.perf_counter()
    with loaded_script(source) as module:
        disciplines, scenario = _top_disciplines(module, mapping)
        if discipline_name:
            candidates = [d for d in _walk(disciplines) if d.name == discipline_name]
            if not candidates:
                msg = f"No discipline {discipline_name} in the script."
                raise WorkerError("not_found", msg)
            process = candidates[0]
            try:
                _point(disciplines, scenario)
                names = set(process.io.input_grammar.names)
                data = {**process.default_input_data}
                data.update({k: v for k, v in process.io.data.items() if k in names})
            except Exception:  # The defaults then, if the process cannot run.
                data = dict(process.default_input_data)
            inputs = _float_names(process.io.input_grammar.names, data)
            outputs = list(process.io.output_grammar.names)
        elif scenario is not None:
            process, inputs, outputs, values = _problem(scenario)
            data = {**process.default_input_data, **values}
        else:
            process = disciplines[0]
            data = dict(process.default_input_data)
            inputs = _float_names(process.io.input_grammar.names, data)
            outputs = list(process.io.output_grammar.names)
        limited = len(inputs) > MAX_VARIABLES or len(outputs) > MAX_VARIABLES
        inputs, outputs = inputs[:MAX_VARIABLES], outputs[:MAX_VARIABLES]
        # Finite differences perturb the inputs: typed as integers, they cannot.
        data = {
            name: np.asarray(value, float) if name in inputs else value
            for name, value in data.items()
        }
        try:
            pairs = _compare(process, inputs, outputs, data)
        except NotImplementedError as error:
            msg = f"GEMSEO cannot differentiate {process.name}: {error}"
            raise WorkerError("not_differentiable", msg) from None
    notes = []
    if _nested(process):
        notes.append(
            "The derivatives through a nested driver are sensitivities of its "
            "optimum; finite differences run it again and may disagree up to "
            "its tolerance."
        )
    return {
        "discipline": process.name,
        "origin": origin(process),
        "mode": str(getattr(process.linearization_mode, "value", "")),
        "inputs": inputs,
        "outputs": outputs,
        "pairs": pairs,
        "tolerance": TOLERANCE,
        "ok": all(pair["ok"] for pair in pairs),
        "limited": limited,
        "notes": notes,
        "seconds": round(time.perf_counter() - started, 3),
    }


def _compare(
    process: Any, inputs: list[str], outputs: list[str], data: dict[str, Any]
) -> list[dict[str, Any]]:
    """The error of each derivative, output by output and input by input."""
    from gemseo.utils.derivatives.approximation_modes import ApproximationMode
    from gemseo.utils.derivatives.derivatives_approx import DisciplineJacApprox

    process.add_differentiated_inputs(inputs)
    process.add_differentiated_outputs(outputs)
    computed = process.linearize(data)
    # A step relative to each value: an absolute one is too large for small values.
    values = np.concatenate([np.atleast_1d(data[name]).ravel() for name in inputs])
    steps = STEP * np.maximum(np.abs(values), 1e-2)
    approximation = DisciplineJacApprox(
        process, ApproximationMode.CENTERED_DIFFERENCES, step=steps
    ).compute_approx_jac(outputs, inputs, input_data=data)
    pairs = []
    for output in outputs:
        for input_ in inputs:
            exact = computed.get(output, {}).get(input_)
            approx = approximation.get(output, {}).get(input_)
            if exact is None or approx is None:
                continue
            exact_array = np.asarray(
                exact.toarray() if hasattr(exact, "toarray") else exact, float
            )
            approx_array = np.asarray(approx, float)
            size = float(np.max(np.abs(approx_array), initial=0.0))
            error = float(np.max(np.abs(exact_array - approx_array), initial=0.0))
            error /= max(1.0, size)
            pairs.append(
                {
                    "output": output,
                    "input": input_,
                    "error": error,
                    "size": size,
                    "ok": error <= TOLERANCE,
                }
            )
    return pairs


def _origins(params: dict[str, Any], context: RequestContext) -> dict[str, str]:
    require_gemseo()
    return origins(str(params.get("source", "")), dict(params.get("mapping") or {}))


def _check(params: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    require_gemseo()
    return check(
        str(params.get("source", "")),
        dict(params.get("mapping") or {}),
        str(params.get("discipline", "")),
    )


def register(server: Any) -> None:
    """Add the derivative methods to the worker."""
    server.add("derivatives.origins", _origins)
    server.add("derivatives.check", _check)
