"""Introspection of components (runs in the worker).

The ports of a component are read from the GEMSEO discipline it creates, so
they are exactly those used at execution time:

- ``analytic``: ``AnalyticDiscipline(expressions)``;
- ``python_function``: ``AutoPyDiscipline(function)``;
- ``python_class``: ``Class(**init_args)``.
"""

import importlib
import inspect
import json
import re
from pathlib import Path
from typing import Any

from gemseo_process_builder.runtime.decorators import COMPONENT_ATTRIBUTE
from gemseo_process_builder.workers.gemseo_loader import require_gemseo
from gemseo_process_builder.workers.script_reader import import_stopping_studies
from gemseo_process_builder.workers.server import RequestContext
from gemseo_process_builder.workers.server import WorkerError

DTYPE_KINDS = {"f": "float", "i": "int", "u": "int", "c": "complex", "b": "int"}


class IntrospectionError(WorkerError):
    """A component whose ports cannot be computed; the message is for the user."""

    def __init__(self, message: str) -> None:
        super().__init__("introspection_failed", message)


def load_attribute(config: dict[str, Any], key: str) -> Any:
    """Load the class or function named ``config[key]`` from the configured module."""
    name = config.get(key)
    if not name:
        msg = f"No {key} is selected."
        raise IntrospectionError(msg)
    try:
        if config.get("module_path"):
            path = Path(config["module_path"])
            if not path.is_file():
                msg = f"The file {path} does not exist."
                raise IntrospectionError(msg)
            module = import_stopping_studies(path)
        elif config.get("module"):
            module = importlib.import_module(config["module"])
        else:
            msg = "No module is selected."
            raise IntrospectionError(msg)
    except IntrospectionError:
        raise
    except BaseException as error:
        msg = f"The module cannot be imported: {type(error).__name__}: {error}"
        raise IntrospectionError(msg) from None
    if not hasattr(module, name):
        msg = f"The module has no {key} named {name}."
        raise IntrospectionError(msg)
    return getattr(module, name)


CONSTANTS = {"pi"}
"""The SymPy names allowed as values in formulas."""

VARIABLE = re.compile(
    r"(?<![A-Za-z0-9_.])([A-Za-z_][A-Za-z0-9_]*)(?![A-Za-z0-9_]|\s*\()"
)
"""A name used as a variable: not called, and not the exponent of a number (1e5)."""


def reserved_names(expressions: dict[str, str]) -> list[str]:
    """The variable names SymPy reads as something else.

    SymPy parses the formulas with its own names: ``S``, ``N``, ``beta``,
    ``gamma``, ``test``… are functions or objects, ``E`` and ``I`` are numbers.
    Used as variables, they fail or silently change the formula.
    """
    import keyword

    import sympy

    used = set(expressions)
    for formula in expressions.values():
        used.update(VARIABLE.findall(formula))
    return sorted(
        name
        for name in used
        if name not in CONSTANTS and (keyword.iskeyword(name) or hasattr(sympy, name))
    )


def check_reserved_names(expressions: dict[str, str]) -> None:
    """Refuse variables named like SymPy's functions and constants."""
    reserved = reserved_names(expressions)
    if reserved:
        names = ", ".join(reserved)
        example = f"{reserved[0]}_1"
        msg = (
            f"{names} cannot be a variable name in formulas: SymPy reads it as a "
            f"function or a constant. Rename it ({example}, for example)."
        )
        raise IntrospectionError(msg)


def create_discipline(kind: str, config: dict[str, Any]) -> tuple[Any, dict[str, str]]:
    """Create the GEMSEO discipline of a component.

    Returns:
        The discipline and the units known from the component definition.
    """
    require_gemseo()
    try:
        if kind == "analytic":
            from gemseo.disciplines.analytic import AnalyticDiscipline

            expressions = config.get("expressions") or {}
            if not expressions:
                msg = "Add at least one expression, like y = x**2."
                raise IntrospectionError(msg)
            check_reserved_names(expressions)
            return AnalyticDiscipline(expressions), {}
        if kind == "python_function":
            from gemseo.disciplines.auto_py import AutoPyDiscipline

            function = load_attribute(config, "function")
            units = getattr(function, COMPONENT_ATTRIBUTE, {}).get("units", {})
            return AutoPyDiscipline(function), dict(units)
        if kind == "python_class":
            cls = load_attribute(config, "class")
            return cls(**(config.get("init_args") or {})), {}
    except IntrospectionError:
        raise
    except BaseException as error:
        msg = f"{type(error).__name__}: {error}"
        raise IntrospectionError(msg) from None
    msg = f"Components of kind {kind} have no introspection."
    raise IntrospectionError(msg)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    try:
        json.dumps(value)
    except TypeError:
        return None
    return value


MAX_DEFAULT_ELEMENTS = 1000
"""Larger default values stay in the discipline: the project keeps their shape
and type only, not hundreds of thousands of numbers."""


def port_from_default(
    name: str, direction: str, default: Any, unit: str | None
) -> dict[str, Any]:
    """Describe a port from its default value, when there is one."""
    port: dict[str, Any] = {"local_name": name, "direction": direction, "unit": unit}
    if default is None:
        port.update({"dtype": "float", "shape": [], "shape_known": False})
        return port
    dtype = getattr(default, "dtype", None)
    if dtype is not None:
        port["dtype"] = DTYPE_KINDS.get(dtype.kind, "object")
        port["shape"] = list(default.shape)
        if default.size > MAX_DEFAULT_ELEMENTS:
            return port
    elif isinstance(default, str):
        port.update({"dtype": "str", "shape": []})
    else:
        port.update({"dtype": "object", "shape": []})
    port["default"] = _jsonable(default)
    return port


def executable_spec(config: dict[str, Any]) -> tuple[Any, Path]:
    """The spec of an executable wrapper and the folder its paths refer to."""
    from gemseo_process_builder.runtime.spec import ExecutableSpec
    from gemseo_process_builder.runtime.spec import load_descriptor

    try:
        if config.get("descriptor_path"):
            return load_descriptor(Path(config["descriptor_path"]))
        if config.get("spec"):
            spec = ExecutableSpec.model_validate(config["spec"])
            return spec, Path(config.get("base_folder_path") or ".")
    except ValueError as error:
        raise IntrospectionError(str(error)) from None
    msg = "Choose a wrapper descriptor (.gpbwrap.json)."
    raise IntrospectionError(msg)


def executable_ports(config: dict[str, Any]) -> list[dict[str, Any]]:
    """The ports of an executable wrapper, from its spec (no GEMSEO needed)."""
    from gemseo_process_builder.runtime.spec import spec_ports

    spec, _ = executable_spec(config)
    return spec_ports(spec)


def surrogate_ports(config: dict[str, Any]) -> list[dict[str, Any]]:
    """The ports of a surrogate, from its metadata.

    A model pickled outside the application has no metadata: it is loaded.
    """
    from gemseo_process_builder.results.surrogates import metadata_ports
    from gemseo_process_builder.results.surrogates import read_metadata

    if not config.get("model_path"):
        msg = "Build a surrogate from a DOE run, or choose one of the project."
        raise IntrospectionError(msg)
    path = Path(config["model_path"])
    if not path.is_file():
        msg = f"The surrogate {path.name} is missing: build it again."
        raise IntrospectionError(msg)
    metadata = read_metadata(path)
    if metadata is not None:
        return metadata_ports(metadata)
    require_gemseo()
    from gemseo import from_pickle
    from gemseo.disciplines.surrogate import SurrogateDiscipline

    try:
        discipline = SurrogateDiscipline(from_pickle(path))
    except Exception as error:
        msg = f"{path.name} is not a regression model of GEMSEO: {error}"
        raise IntrospectionError(msg) from None
    inputs = discipline.io.input_grammar
    ports = [
        port_from_default(name, "in", inputs.defaults.get(name), None)
        for name in inputs.names
    ]
    return ports + [
        port_from_default(name, "out", None, None)
        for name in discipline.io.output_grammar.names
    ]


def introspect(kind: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    """The ports of a component."""
    if kind == "executable":
        return executable_ports(config)
    if kind == "surrogate":
        return surrogate_ports(config)
    discipline, units = create_discipline(kind, config)
    inputs = discipline.io.input_grammar
    outputs = discipline.io.output_grammar
    ports = [
        port_from_default(name, "in", inputs.defaults.get(name), units.get(name))
        for name in inputs.names
    ]
    for name in outputs.names:
        port = port_from_default(name, "out", None, units.get(name))
        if kind == "analytic":
            port.update({"shape": [1], "shape_known": True})
        ports.append(port)
    return ports


def init_signature(config: dict[str, Any]) -> list[dict[str, Any]]:
    """The parameters of a discipline class constructor."""
    require_gemseo()
    cls = load_attribute(config, "class")
    parameters = []
    for parameter in list(inspect.signature(cls.__init__).parameters.values())[1:]:
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        has_default = parameter.default is not inspect.Parameter.empty
        annotation = parameter.annotation
        parameters.append(
            {
                "name": parameter.name,
                "annotation": ""
                if annotation is inspect.Parameter.empty
                else getattr(annotation, "__name__", str(annotation)),
                "required": not has_default,
                "default": _jsonable(parameter.default) if has_default else None,
            }
        )
    return parameters


def _introspect(
    params: dict[str, Any], context: RequestContext
) -> list[dict[str, Any]]:
    return introspect(str(params.get("kind")), dict(params.get("config") or {}))


def _init_signature(
    params: dict[str, Any], context: RequestContext
) -> list[dict[str, Any]]:
    return init_signature(dict(params.get("config") or {}))


def register(server: Any) -> None:
    """Add the component methods to the worker."""
    server.add("component.introspect", _introspect)
    server.add("component.init_signature", _init_signature)
