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

import ast
import inspect
import json
import math
import os
import re
import runpy
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from gemseo_process_builder.codegen.generator import GENERATED_BY
from gemseo_process_builder.workers.gemseo_loader import require_gemseo
from gemseo_process_builder.workers.script_check import check_script
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
    algorithms: dict[int, dict[str, Any]] = field(default_factory=dict)
    """The algorithm set on each nested scenario (``set_algorithm``), by ``id``."""

    pickles: dict[int, str] = field(default_factory=dict)
    """The file each unpickled object comes from (surrogate models), by ``id``."""

    validate_data: bool = True
    """Whether the script left GEMSEO's checks of the data on (fast mode)."""

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
    import gemseo

    originals = {
        "from_pickle": gemseo.from_pickle,
        "execute": Discipline.execute,
        "scenario_execute": BaseScenario.execute,
        "set_algorithm": BaseScenario.set_algorithm,
        "add_constraint": BaseScenario.add_constraint,
        "add_observable": BaseScenario.add_observable,
    }

    def scenario_execute(self: Any, *args: Any, **settings: Any) -> None:
        record.executed = self
        record.algorithm = dict(settings)
        if args or settings.get("algo_settings_model") is not None:
            record.algorithm["settings_model"] = True
        raise StudyStopped

    def set_algorithm(self: Any, *args: Any, **settings: Any) -> None:
        algorithm = dict(settings)
        if args or settings.get("algo_settings_model") is not None:
            algorithm["settings_model"] = True
        record.algorithms[id(self)] = algorithm
        originals["set_algorithm"](self, *args, **settings)

    def execute(self: Any, *args: Any, **kwargs: Any) -> Any:
        if record.scenarios and not _holds_scenario(self):
            # Values computed before the scenario, like initial values: allowed.
            return originals["execute"](self, *args, **kwargs)
        # The process of the script, or a study holding its scenarios.
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

    def from_pickle(file_path: Any, *args: Any, **kwargs: Any) -> Any:
        value = originals["from_pickle"](file_path, *args, **kwargs)
        record.pickles[id(value)] = str(Path(file_path).resolve())
        record.kept.append(value)
        return value

    gemseo.from_pickle = from_pickle
    Discipline.execute = execute
    BaseScenario.execute = scenario_execute
    BaseScenario.set_algorithm = set_algorithm
    BaseScenario.add_constraint = add_constraint
    BaseScenario.add_observable = add_observable
    _active.append(record)
    try:
        yield record
    finally:
        _active.pop()
        from gemseo.utils.global_configuration import _configuration

        record.validate_data = bool(_configuration.validate_input_data)
        gemseo.from_pickle = originals["from_pickle"]
        Discipline.execute = originals["execute"]
        BaseScenario.execute = originals["scenario_execute"]
        BaseScenario.set_algorithm = originals["set_algorithm"]
        BaseScenario.add_constraint = originals["add_constraint"]
        BaseScenario.add_observable = originals["add_observable"]


def _holds_scenario(discipline: Any) -> bool:
    """Whether a discipline runs a scenario: an adapter, or a group holding one."""
    from gemseo.disciplines.scenario_adapters.mdo_scenario_adapter import (
        MDOScenarioAdapter,
    )

    if isinstance(discipline, MDOScenarioAdapter):
        return True
    return any(
        _holds_scenario(inner) for inner in getattr(discipline, "disciplines", [])
    )


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


def forget_modules(folder: Path) -> None:
    """Forget the modules imported from a folder, so that they are read again.

    The modules of a project (its own files, next to its script) may have been
    edited since the worker imported them.
    """

    # Strings, not resolved paths: there are thousands of modules to look at.
    def prefix(path: str) -> str:
        return os.path.join(os.path.normcase(os.path.abspath(path)), "")

    inside = prefix(str(folder))
    # Not those of a Python installed in the folder (a .venv): GEMSEO is there.
    installed = (prefix(sys.prefix), prefix(sys.base_prefix))
    for name, module in list(sys.modules.items()):
        file = getattr(module, "__file__", None)
        if not isinstance(file, str):
            continue
        path = os.path.normcase(os.path.abspath(file))
        if path.startswith(inside) and not path.startswith(installed):
            del sys.modules[name]


def run_script(path: Path) -> Recording:
    """Run a script until its study would start; what it built."""
    folder = str(path.parent)
    previous = os.getcwd()
    sys.path.insert(0, folder)
    os.chdir(folder)
    forget_modules(path.parent.resolve())
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
        from gemseo.disciplines.remapping import RemappingDiscipline
        from gemseo.disciplines.scenario_adapters.mdo_scenario_adapter import (
            MDOScenarioAdapter,
        )
        from gemseo.disciplines.surrogate import SurrogateDiscipline
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
        if isinstance(discipline, RemappingDiscipline):
            return self._remapped(discipline, arguments)
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
        if isinstance(discipline, SurrogateDiscipline):
            surrogate = self._surrogate(discipline, arguments, name)
            if surrogate is not None:
                return surrogate
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

    def _remapped(self, discipline: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        """The component a ``RemappingDiscipline`` renames the variables of.

        Its renamed variables become the global names of its ports: a link
        between differently named variables in the diagram.
        """
        inner = arguments.get("discipline")
        node = self.node(inner)
        if node.get("type") != "component":
            self.warnings.append(
                f"{node['name']}: the renamed variables of a group are left out."
            )
            return node
        ports = {(p["local_name"], p["direction"]): p for p in node.get("ports", [])}
        for key, direction in (("input_mapping", "in"), ("output_mapping", "out")):
            for global_name, local_name in (arguments.get(key) or {}).items():
                if global_name == local_name:
                    continue
                port = ports.setdefault(
                    (local_name, direction),
                    {"local_name": local_name, "direction": direction},
                )
                port["global_name"] = global_name
        # Values set on the wrapper are under the global names.
        local_names = {
            global_name: local_name
            for global_name, local_name in (
                arguments.get("input_mapping") or {}
            ).items()
        }
        for typed in self._typed(discipline, node["name"]):
            local = local_names.get(typed["local_name"], typed["local_name"])
            port = ports.setdefault(
                (local, "in"), {"local_name": local, "direction": "in"}
            )
            port.update(default=typed["default"], default_text=typed["default_text"])
        node["ports"] = list(ports.values())
        return node

    def _surrogate(
        self, discipline: Any, arguments: dict[str, Any], name: str
    ) -> dict[str, Any] | None:
        """A surrogate component, when its model comes from a file.

        A model pickled by the application has its metadata next to it; one
        pickled by the user is described by its type.
        """
        from gemseo_process_builder.results.surrogates import read_metadata

        model = arguments.get("surrogate")
        file = self.record.pickles.get(id(model)) if model is not None else None
        if isinstance(model, str | Path):
            file = str(Path(model).resolve())
        if not file:
            return None
        metadata = read_metadata(Path(file))
        if metadata is None:
            summary = (
                f"{type(discipline.regression_model).__name__} from {Path(file).name}"
            )
            config = {"model_path": file, "summary": summary}
            return self._component(name, "surrogate", config, discipline)
        config = {
            "surrogate_id": metadata.id,
            "model_path": file,
            "summary": metadata.summary(),
        }
        return self._component(name, "surrogate", config, discipline)

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
        # The algorithm of the study executed, or the one set on a nested one.
        recorded = (
            self.record.algorithm
            if scenario is self.record.executed
            else self.record.algorithms.get(id(scenario))
        )
        if recorded is not None:
            algorithm = dict(recorded)
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
            processes = algorithm.pop("n_processes", None)
            config["execution"] = {"validate_data": self.record.validate_data}
            if isinstance(processes, int) and processes > 1:
                config["execution"]["n_processes"] = processes
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


def node_id(names: list[str]) -> str:
    """The id of a node read from a script, made of its names from the root.

    It is the same each time the script is read: runs refer to it.
    """
    slug = ".".join(re.sub(r"[^A-Za-z0-9_]+", "_", name) for name in names)
    return f"n-{slug}"


def _positions(
    node: dict[str, Any], layout: dict[str, Any], names: tuple[str, ...] = ()
) -> None:
    """Give the nodes their ids, and place the children of containers in a row.

    The page then lays them out.
    """
    for index, child in enumerate(node.get("children", [])):
        path = (*names, child["name"])
        child["id"] = node_id(list(path))
        layout[child["id"]] = {"x": 60.0 + 300.0 * index, "y": 60.0}
        _positions(child, layout, path)


def _components(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if node.get("type") == "component":
        yield node
    for child in node.get("children", []):
        yield from _components(child)


def _namespaces(root: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    """Turn namespaced variables (``Front:mass``) into isolated components and links.

    A component whose variables are renamed ``<its name>:<variable>`` is an
    isolated instance; another component reading ``Front:mass`` is linked to the
    ``mass`` output of ``Front``.

    Returns:
        The links to add to the project.
    """
    components = list(_components(root))
    outputs: dict[str, tuple[str, str]] = {}
    for node in components:
        prefix = node["name"] + ":"
        own = [
            port
            for port in node.get("ports", [])
            if port.get("global_name") == prefix + port["local_name"]
        ]
        if not own:
            continue
        node["isolated"] = True
        for port in node["ports"]:
            if any(port is kept for kept in own):
                del port["global_name"]
                if port["direction"] == "out":
                    outputs[prefix + port["local_name"]] = (
                        node["id"],
                        port["local_name"],
                    )
            elif "global_name" not in port:
                # Shared with the other disciplines: not namespaced.
                port["global_name"] = port["local_name"]
    links = []
    for node in components:
        for port in node.get("ports", []):
            name = port.get("global_name") or ""
            if ":" not in name:
                continue
            del port["global_name"]
            source = outputs.get(name)
            if source is not None and port["direction"] == "in":
                links.append(
                    {
                        "source": {"node": source[0], "port": source[1]},
                        "target": {"node": node["id"], "port": port["local_name"]},
                    }
                )
            else:
                warnings.append(
                    f"{node['name']}: {port['local_name']} is no longer named {name}."
                )
    return links


def script_metadata(path: Path) -> dict[str, str]:
    """The name and description of the project of a script, from its docstring.

    A script the application wrote starts with the name of the project and its
    description; the script of someone else is named after its file.
    """
    try:
        docstring = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    except (SyntaxError, UnicodeDecodeError, OSError):
        docstring = None
    if not docstring:
        return {"name": path.stem, "description": f"Read from {path.name}."}
    paragraphs = [part.strip() for part in docstring.split("\n\n")]
    generated = [part.startswith(GENERATED_BY) for part in paragraphs]
    if not any(generated[1:]):
        return {"name": path.stem, "description": docstring.strip()}
    end = generated.index(True, 1)
    return {
        "name": paragraphs[0].removesuffix("."),
        # Its paragraphs were wrapped to the line length.
        "description": "\n\n".join(
            " ".join(part.split()) for part in paragraphs[1:end]
        ),
    }


MAX_FINDINGS = 8
"""The reasons shown at most when a script is refused."""


def refuse_other_scripts(path: Path) -> None:
    """Refuse, before running it, a script that is not a GEMSEO 6 study.

    Raises:
        WorkerError: ``not_gemseo6`` with the reasons, for the user.
    """
    check = check_script(path)
    if check.ok:
        return
    if not check.findings:
        msg = (
            f"{path.name} does not import GEMSEO: it is not a GEMSEO study, "
            "and it was not run."
        )
        raise WorkerError("not_gemseo6", msg)
    reasons = [finding.describe(path.parent) for finding in check.findings]
    more = len(reasons) - MAX_FINDINGS
    lines = [f"- {reason}" for reason in reasons[:MAX_FINDINGS]]
    if more > 0:
        lines.append(f"- and {more} more.")
    msg = f"{path.name} is not a GEMSEO 6 study, and it was not run:\n" + "\n".join(
        lines
    )
    raise WorkerError("not_gemseo6", msg)


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
    refuse_other_scripts(path)
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
    if node.get("type") == "assembly":
        # The chain or the MDA of a script without scenario: the model itself.
        root = {**node, "id": "n-root", "name": "Model"}
    else:
        root = {
            "type": "assembly",
            "id": "n-root",
            "name": "Model",
            "mode": "auto",
            "children": [node],
        }
    layout: dict[str, Any] = {}
    _positions(root, layout)
    links = _namespaces(root, converter.warnings)
    project = {
        "metadata": script_metadata(path),
        "root": root,
        "links": links,
        "layout": {"nodes": layout},
    }
    return {"project": project, "warnings": converter.warnings}


def _read(params: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    return read_script(Path(str(params.get("path", ""))))


def register(server: Any) -> None:
    """Add ``script.read`` to the worker."""
    server.add("script.read", _read)
