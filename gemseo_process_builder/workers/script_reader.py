"""Reading a GEMSEO script into a project (runs in the worker; SPEC § 3.5).

GEMSEO has no project format: a study is a Python script, written freely.
Its text cannot be read reliably, so the script is run, as ``python
script.py`` would, while the calls that build the study are recorded:

- the arguments every discipline (and scenario) is built with, through
  ``Discipline.__new__``;
- ``add_constraint`` and ``add_observable``;
- ``execute`` of a scenario: its algorithm and settings are recorded, and the
  study stops there, before anything is computed.

A script without scenario stops at the first discipline it executes (an MDA,
a chain…), which becomes the process of the project. The recorded objects
are then turned into the nodes of a project; what cannot be represented is
reported.
"""

import inspect
import json
import math
import os
import runpy
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from gemseo_process_builder.workers.gemseo_loader import require_gemseo
from gemseo_process_builder.workers.server import RequestContext
from gemseo_process_builder.workers.server import WorkerError


class StudyStopped(BaseException):
    """Raised where the script would start computing.

    A ``BaseException``, so that ``except Exception`` in the script does not
    catch it.
    """


@dataclass
class Recording:
    """What a script did to build its study."""

    calls: dict[int, tuple[type, dict[str, Any]]] = field(default_factory=dict)
    """The arguments of the constructor of each discipline, by ``id``."""

    kept: list[Any] = field(default_factory=list)
    """The recorded objects, kept alive so that their ids stay unique."""

    scenarios: list[Any] = field(default_factory=list)
    constraints: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    observables: dict[int, list[str]] = field(default_factory=dict)
    executed: Any = None
    """The scenario or the discipline the script executed first."""

    algorithm: dict[str, Any] = field(default_factory=dict)

    def arguments(self, instance: Any) -> dict[str, Any]:
        """The arguments an object was built with, by parameter name."""
        return self.calls.get(id(instance), (type(instance), {}))[1]


def _bound(cls: type, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """The arguments of a constructor call, by parameter name."""
    signature = inspect.signature(vars(cls).get("__init__") or cls.__init__)  # type: ignore[misc]
    try:
        bound = signature.bind(None, *args, **kwargs)
    except (TypeError, ValueError):
        return dict(kwargs)
    arguments = dict(bound.arguments)
    arguments.pop(next(iter(arguments)), None)  # self
    for name, parameter in signature.parameters.items():
        if parameter.kind is parameter.VAR_KEYWORD and name in arguments:
            arguments.update(arguments.pop(name))
    return arguments


_active: list[Recording] = []
"""The recording in progress, if any."""


def _new(cls: type, *args: Any, **kwargs: Any) -> Any:
    """``object.__new__``, recording the constructor calls while a script is read."""
    instance: Any = object.__new__(cls)
    if _active:
        record = _active[-1]
        record.calls[id(instance)] = (cls, _bound(cls, args, kwargs))
        record.kept.append(instance)
        if _is_scenario(instance):
            record.scenarios.append(instance)
    return instance


def _is_scenario(instance: Any) -> bool:
    from gemseo.scenarios.base_scenario import BaseScenario

    return isinstance(instance, BaseScenario)


def _install_new() -> None:
    """Record constructor calls, once for all.

    A ``__new__`` set on a class cannot be removed without breaking it: CPython
    then passes the arguments of the constructor to ``object.__new__``.
    """
    from gemseo.core.discipline import Discipline
    from gemseo.scenarios.base_scenario import BaseScenario

    for cls in (Discipline, BaseScenario):  # A scenario is not a discipline.
        if vars(cls).get("__new__") is not _new:
            cls.__new__ = _new


@contextmanager
def recording() -> Iterator[Recording]:
    """Record how disciplines and scenarios are built; stop studies."""
    from gemseo.core.discipline import Discipline
    from gemseo.scenarios.base_scenario import BaseScenario

    _install_new()
    record = Recording()
    originals = {
        "execute": Discipline.execute,
        "scenario_execute": BaseScenario.execute,
        "add_constraint": BaseScenario.add_constraint,
        "add_observable": BaseScenario.add_observable,
    }

    def scenario_execute(self: Any, *args: Any, **settings: Any) -> None:
        record.executed = self
        record.algorithm = dict(settings)
        if args or settings.get("algo_settings_model") is not None:
            record.algorithm["settings_model"] = True
        raise StudyStopped

    def execute(self: Any, *args: Any, **kwargs: Any) -> Any:
        if record.scenarios:
            # Values computed before the scenario, like initial values: allowed.
            return originals["execute"](self, *args, **kwargs)
        record.executed = self
        raise StudyStopped

    def add_constraint(self: Any, output_name: Any, *args: Any, **kwargs: Any) -> Any:
        method = originals["add_constraint"]
        arguments = _bound_method(method, output_name, args, kwargs)
        record.constraints.setdefault(id(self), []).append(arguments)
        return method(self, output_name, *args, **kwargs)

    def add_observable(self: Any, output_names: Any, *args: Any, **kwargs: Any) -> Any:
        names = [output_names] if isinstance(output_names, str) else list(output_names)
        record.observables.setdefault(id(self), []).extend(names)
        return originals["add_observable"](self, output_names, *args, **kwargs)

    Discipline.execute = execute
    BaseScenario.execute = scenario_execute
    BaseScenario.add_constraint = add_constraint
    BaseScenario.add_observable = add_observable
    _active.append(record)
    try:
        yield record
    finally:
        _active.pop()
        Discipline.execute = originals["execute"]
        BaseScenario.execute = originals["scenario_execute"]
        BaseScenario.add_constraint = originals["add_constraint"]
        BaseScenario.add_observable = originals["add_observable"]


def _bound_method(
    method: Any, first: Any, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    try:
        bound = inspect.signature(method).bind(None, first, *args, **kwargs)
    except TypeError:
        return {"output_name": first, **kwargs}
    arguments = dict(bound.arguments)
    arguments.pop(next(iter(arguments)), None)
    return arguments


def import_stopping_studies(path: Path) -> Any:
    """Import a Python file without running the study it may start.

    A script written by hand may build and run its study when imported: it
    stops where it would start computing, and what it defined before is kept
    (its functions and classes are usually defined first).
    """
    from gemseo_process_builder.catalog.scanner import import_file

    with recording():
        return import_file(path, keep_on=(StudyStopped,))


def run_script(path: Path) -> Recording:
    """Run a script until its study would start; what it built."""
    folder = str(path.parent)
    previous = os.getcwd()
    sys.path.insert(0, folder)
    os.chdir(folder)
    try:
        with recording() as record:
            try:
                runpy.run_path(str(path), run_name="__main__")
            except StudyStopped:
                pass
            except SystemExit:
                pass
    finally:
        os.chdir(previous)
        if folder in sys.path:
            sys.path.remove(folder)
    return record


def _plain(value: Any) -> Any:
    """A JSON value, or ``None`` when it has none."""
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return None
    return value


def _numbers(values: Any) -> list[float | None]:
    return [None if not math.isfinite(v) else float(v) for v in list(values)]


def grid_levels(
    samples: Any, variables: list[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """The levels of a parametric study whose samples are all the combinations.

    Args:
        samples: The samples of a ``CustomDOE``, one row per evaluation.
        variables: The design variables, whose elements are the columns.

    Returns:
        One level per variable (evenly spaced values, or a list), or ``None``
        when the samples are not every combination of a few values each.
    """
    from numpy import allclose
    from numpy import asarray
    from numpy import linspace
    from numpy import unique

    rows = asarray(samples, dtype=float)
    if rows.ndim != 2 or any(v["size"] != 1 for v in variables):
        return None
    if rows.shape[1] != len(variables):
        return None
    values = [unique(rows[:, column]) for column in range(rows.shape[1])]
    combinations = math.prod(len(column) for column in values)
    if combinations != len(rows) or len(unique(rows, axis=0)) != len(rows):
        return None
    levels = []
    for variable, column in zip(variables, values, strict=True):
        spaced = linspace(column[0], column[-1], len(column))
        if len(column) > 2 and allclose(column, spaced):
            levels.append(
                {
                    "variable": variable["variable"],
                    "lower": float(column[0]),
                    "upper": float(column[-1]),
                    "count": len(column),
                }
            )
        else:
            levels.append(
                {
                    "variable": variable["variable"],
                    "mode": "list",
                    "values": [float(value) for value in column],
                }
            )
    return levels


class Converter:
    """Turn the objects a script built into the nodes of a project."""

    def __init__(self, record: Recording, script: Path) -> None:
        self.record = record
        self.script = script.resolve()
        self.warnings: list[str] = []
        self.names: set[str] = set()

    def _name(self, wanted: str) -> str:
        """A node name not used yet."""
        name = wanted or "Discipline"
        index = 2
        while name in self.names:
            name = f"{wanted}_{index}"
            index += 1
        self.names.add(name)
        return name

    def node(self, discipline: Any) -> dict[str, Any]:
        """The node of a discipline, a group or a nested scenario."""
        from gemseo.core.chains.chain import MDOChain
        from gemseo.core.chains.parallel_chain import MDOParallelChain
        from gemseo.disciplines.analytic import AnalyticDiscipline
        from gemseo.disciplines.auto_py import AutoPyDiscipline
        from gemseo.disciplines.scenario_adapters.mdo_scenario_adapter import (
            MDOScenarioAdapter,
        )
        from gemseo.mda.base_mda import BaseMDA
        from gemseo.scenarios.base_scenario import BaseScenario

        from gemseo_process_builder.runtime.executable import ExecutableDiscipline

        arguments = self.record.arguments(discipline)
        if isinstance(discipline, MDOScenarioAdapter):
            scenario = arguments.get("scenario")
            node = self.scenario(scenario)
            node["config"]["interface"] = {
                "inputs": list(arguments.get("input_names") or []),
                "outputs": list(arguments.get("output_names") or []),
            }
            return node
        if isinstance(discipline, BaseScenario):
            return self.scenario(discipline)
        name = self._name(str(getattr(discipline, "name", "")))
        if isinstance(discipline, BaseMDA | MDOParallelChain | MDOChain):
            children = [self.node(d) for d in arguments.get("disciplines") or []]
            if isinstance(discipline, BaseMDA):
                mode = "mda"
                if type(discipline).__name__ != "MDAChain":
                    self.warnings.append(
                        f"{name}: the {type(discipline).__name__} is read as an MDA "
                        "chain (MDAChain), which solves the same couplings."
                    )
            else:
                mode = (
                    "parallel" if isinstance(discipline, MDOParallelChain) else "chain"
                )
            return {
                "type": "assembly",
                "name": name,
                "mode": mode,
                "children": children,
            }
        if isinstance(discipline, AnalyticDiscipline):
            expressions = arguments.get("expressions") or discipline.expressions
            formulas = {str(k): str(v) for k, v in expressions.items()}
            return self._component(
                name, "analytic", {"expressions": formulas}, discipline
            )
        if isinstance(discipline, AutoPyDiscipline):
            function = arguments.get("py_func")
            return self._component(
                name,
                "python_function",
                self._source(function, name, "function"),
                discipline,
            )
        if isinstance(discipline, ExecutableDiscipline):
            spec = arguments.get("spec")
            config: dict[str, Any] = {
                "spec": spec.model_dump(mode="json") if spec is not None else {},
                "base_folder_path": str(arguments.get("base_folder") or "."),
            }
            return self._component(name, "executable", config, discipline)
        return self._component(
            name, "python_class", self._class(discipline, name), discipline
        )

    def _component(
        self, name: str, kind: str, config: dict[str, Any], discipline: Any
    ) -> dict[str, Any]:
        node: dict[str, Any] = {
            "type": "component",
            "kind": kind,
            "name": name,
            "config": config,
        }
        node["ports"] = self._typed(discipline, name)
        return node

    def _typed(self, discipline: Any, name: str) -> list[dict[str, Any]]:
        """The inputs whose value the script set after building the discipline.

        They are the values typed in the diagram: the default values of the
        discipline now, compared with those of the same discipline just built.
        """
        from numpy import array_equal
        from numpy import asarray

        try:
            current = dict(discipline.io.input_grammar.defaults)
            built = type(discipline)(**self.record.arguments(discipline))
            reference = dict(built.io.input_grammar.defaults)
        except Exception:  # An error of user code: no values then.
            return []
        ports = []
        for variable, value in current.items():
            before = reference.get(variable)
            if before is not None and array_equal(asarray(value), asarray(before)):
                continue
            plain = _plain(value)
            if plain is None:
                self.warnings.append(
                    f"{name}: the value set on {variable} is not a plain value; "
                    "it is left out."
                )
                continue
            if isinstance(plain, list) and len(plain) == 1:
                plain = plain[0]
            text = json.dumps(plain) if isinstance(plain, list) else str(plain)
            ports.append(
                {
                    "local_name": variable,
                    "direction": "in",
                    "default": plain,
                    "default_text": text,
                }
            )
        return ports

    def _source(self, obj: Any, name: str, key: str) -> dict[str, Any]:
        """Where a function or a class is defined: a module, or a file."""
        module = getattr(obj, "__module__", "") or ""
        qualified = getattr(obj, "__qualname__", "")
        if "<" in qualified or "." in qualified:
            self.warnings.append(
                f"{name}: {qualified} is defined inside a function; "
                "move it to the module level to use it."
            )
        if module == "__main__":
            # Defined in the script, run as __main__.
            file = self.script
        else:
            try:
                file = Path(inspect.getsourcefile(obj) or "").resolve()
            except TypeError:
                file = Path()
        installed = module and module != "__main__" and not module.startswith("gpb_")
        if installed and file.is_file() and file.parent != self.script.parent:
            return {"module": module, key: obj.__name__}
        return {
            "module_path": str(file if file.is_file() else self.script),
            key: obj.__name__,
        }

    def _class(self, discipline: Any, name: str) -> dict[str, Any]:
        """A discipline class, with the arguments it was built with."""
        cls = type(discipline)
        config = self._source(cls, name, "class")
        init_args = {}
        for parameter, value in self.record.arguments(discipline).items():
            plain = _plain(value)
            if plain is None and value is not None:
                self.warnings.append(
                    f"{name}: the argument {parameter} of {cls.__name__} is not a "
                    "plain value; it is left out."
                )
                continue
            init_args[parameter] = plain
        config["init_args"] = init_args
        return config

    def design_space(self, space: Any) -> list[dict[str, Any]]:
        """The design variables of a design space."""
        variables = []
        for variable in space.variable_names:
            item: dict[str, Any] = {
                "variable": variable,
                "size": int(space.get_size(variable)),
                "lower": _numbers(space.get_lower_bound(variable)),
                "upper": _numbers(space.get_upper_bound(variable)),
                "type": "integer"
                if "int" in str(space.get_type(variable))
                else "float",
            }
            try:
                item["value"] = _numbers(space.get_current_value([variable]))
            except (KeyError, ValueError):
                item["value"] = []
            variables.append(item)
        return variables

    def scenario(self, scenario: Any) -> dict[str, Any]:
        """The driver of a scenario, with its disciplines inside."""
        from gemseo.scenarios.doe_scenario import DOEScenario

        arguments = self.record.arguments(scenario)
        kind = "doe" if isinstance(scenario, DOEScenario) else "optimization"
        # GEMSEO names a scenario after its class by default.
        given = str(getattr(scenario, "name", ""))
        default = "DOE" if kind == "doe" else "Optimizer"
        name = self._name(default if given in ("", type(scenario).__name__) else given)
        objectives = arguments.get("objective_name") or ""
        objectives = [objectives] if isinstance(objectives, str) else list(objectives)
        sense = "maximize" if arguments.get("maximize_objective") else "minimize"
        formulation = str(arguments.get("formulation_name") or "MDF")
        settings = {
            key: _plain(value)
            for key, value in arguments.items()
            if key
            not in (
                "disciplines",
                "objective_name",
                "design_space",
                "name",
                "maximize_objective",
                "formulation_name",
                "formulation_settings_model",
            )
            and _plain(value) is not None
        }
        constraints = []
        for call in self.record.constraints.get(id(scenario), []):
            outputs = call.get("output_name")
            for output in (
                [outputs] if isinstance(outputs, str) else list(outputs or [])
            ):
                constraint_type = str(
                    getattr(
                        call.get("constraint_type"),
                        "value",
                        call.get("constraint_type") or "eq",
                    )
                )
                constraints.append(
                    {
                        "variable": output,
                        "type": constraint_type,
                        "operator": ">=" if call.get("positive") else "<=",
                        "value": float(call.get("value") or 0),
                    }
                )
        observables = self.record.observables.get(id(scenario), [])
        config: dict[str, Any] = {
            "design_space": self.design_space(arguments.get("design_space")),
            "formulation": {"name": formulation, "settings": settings},
            "constraints": constraints,
        }
        if kind == "doe":
            config["responses"] = objectives + [
                n for n in observables if n not in objectives
            ]
        else:
            config["objectives"] = [{"variable": o, "sense": sense} for o in objectives]
            config["observables"] = observables
        if scenario is self.record.executed:
            algorithm = dict(self.record.algorithm)
            if algorithm.pop("settings_model", False):
                self.warnings.append(
                    f"{name}: the algorithm settings given as a model are left out."
                )
            algo_name = str(algorithm.pop("algo_name", "") or "")
            samples = algorithm.pop("samples", None)
            if algo_name == "CustomDOE" and samples is not None:
                levels = grid_levels(samples, config["design_space"])
                if levels is not None:
                    # Every combination of a few values: a parametric study.
                    kind = "parametric"
                    config["levels"] = levels
                    config.pop("design_space")
                else:
                    self.warnings.append(
                        f"{name}: the samples given to CustomDOE are not every "
                        "combination of a few values; the study draws as many "
                        "samples with LHS instead."
                    )
                    algo_name = "LHS"
                    algorithm["n_samples"] = len(samples)
            config["algorithm"] = {
                "name": algo_name,
                "settings": {
                    k: _plain(v) for k, v in algorithm.items() if _plain(v) is not None
                },
            }
        disciplines = arguments.get("disciplines") or []
        return {
            "type": "driver",
            "kind": kind,
            "name": name,
            "config": config,
            "children": [self.node(d) for d in disciplines],
        }


def _positions(node: dict[str, Any], layout: dict[str, Any], path: str = "") -> None:
    """Place the children of each container in a row (the page can lay them out)."""
    for index, child in enumerate(node.get("children", [])):
        child["id"] = f"n-{path}{index}-{child['name']}".replace(" ", "_")
        layout[child["id"]] = {"x": 60.0 + 300.0 * index, "y": 60.0}
        _positions(child, layout, f"{path}{index}-")


def read_script(path: Path) -> dict[str, Any]:
    """The project of a GEMSEO script, and what could not be kept.

    Returns:
        ``project``: a project document; ``warnings``: messages for the user.
    """
    require_gemseo()
    # The script runs in its folder: a relative path would no longer lead to it.
    path = path.resolve()
    if not path.is_file():
        msg = f"{path} does not exist."
        raise WorkerError("not_found", msg)
    try:
        record = run_script(path)
    except Exception as error:
        failure = f"{type(error).__name__}: {error}"
        msg = f"The script failed before its study started: {failure}"
        raise WorkerError("script_error", msg) from None
    target = record.executed or (record.scenarios[-1] if record.scenarios else None)
    if target is None:
        msg = (
            "The script builds no scenario and executes no discipline: nothing to read."
        )
        raise WorkerError("script_error", msg)
    converter = Converter(record, path)
    node = converter.node(target)
    root = {
        "type": "assembly",
        "id": "n-root",
        "name": "Model",
        "mode": "auto",
        "children": [node],
    }
    layout: dict[str, Any] = {}
    _positions(root, layout)
    project = {
        "metadata": {"name": path.stem, "description": f"Read from {path.name}."},
        "root": root,
        "layout": {"nodes": layout},
    }
    return {"project": project, "warnings": converter.warnings}


def _read(params: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    return read_script(Path(str(params.get("path", ""))))


def register(server: Any) -> None:
    """Add ``script.read`` to the worker."""
    server.add("script.read", _read)
