"""The algorithms GEMSEO offers, and whether they can solve a problem.

The same rules as the driver editor of GEMSEO Process Builder (SPEC § 6.4),
read from GEMSEO's algorithm descriptions; this package does not depend on the
application.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError

from gemseo_claude_pilot.snapshots import DRIVER_NAMES
from gemseo_claude_pilot.snapshots import DriverKind
from gemseo_claude_pilot.snapshots import ProblemSnapshot


@dataclass(frozen=True)
class AlgorithmInfo:
    """What an algorithm can handle, and the model of its settings."""

    name: str
    kind: DriverKind
    settings_model: type[BaseModel]
    description: str = ""
    handle_equality_constraints: bool = False
    handle_inequality_constraints: bool = False
    handle_multiobjective: bool = False
    handle_integer_variables: bool = False
    require_gradient: bool = False


@cache
def gemseo_algorithms(kind: DriverKind) -> Mapping[str, AlgorithmInfo]:
    """The installed GEMSEO algorithms of a kind, by name."""
    factory: Any
    if kind == "optimization":
        from gemseo.algos.opt.factory import OptimizationLibraryFactory

        factory = OptimizationLibraryFactory()
    else:
        from gemseo.algos.doe.factory import DOELibraryFactory

        factory = DOELibraryFactory()
    algorithms = {}
    for name in factory.algorithms:
        library = factory.get_class(factory.algo_names_to_libraries[name])
        # DOE descriptions have no capabilities: they handle any problem.
        info = library.ALGORITHM_INFOS[name]
        algorithms[name] = AlgorithmInfo(
            name=name,
            kind=kind,
            settings_model=info.Settings,
            description=info.description,
            handle_equality_constraints=getattr(
                info, "handle_equality_constraints", False
            ),
            handle_inequality_constraints=getattr(
                info, "handle_inequality_constraints", False
            ),
            handle_multiobjective=getattr(info, "handle_multiobjective", False),
            handle_integer_variables=getattr(info, "handle_integer_variables", False),
            require_gradient=getattr(info, "require_gradient", False),
        )
    return algorithms


def incompatibilities(algorithm: AlgorithmInfo, problem: ProblemSnapshot) -> list[str]:
    """Why an algorithm cannot solve a problem, if it cannot."""
    if algorithm.kind != problem.driver_kind:
        return [f"cannot drive {DRIVER_NAMES[problem.driver_kind]}"]
    if algorithm.kind == "doe":
        return []
    reasons = []
    types = {constraint.type for constraint in problem.constraints}
    if "eq" in types and not algorithm.handle_equality_constraints:
        reasons.append("does not handle equality constraints")
    if "ineq" in types and not algorithm.handle_inequality_constraints:
        reasons.append("does not handle inequality constraints")
    integers = any(variable.integer for variable in problem.variables)
    if integers and not algorithm.handle_integer_variables:
        reasons.append("does not handle integer variables")
    if algorithm.require_gradient and problem.gradients == "none":
        reasons.append("needs gradients, which this problem does not provide")
    return reasons


def default_settings(algorithm: AlgorithmInfo) -> dict[str, Any]:
    """The defaults of the settings of an algorithm that have a plain value."""
    defaults: dict[str, Any] = {}
    for name, field in algorithm.settings_model.model_fields.items():
        if field.is_required() or field.default_factory is not None:
            continue
        value = field.default
        if value is None or isinstance(value, bool | int | float | str):
            defaults[name] = value
    return defaults


def same_setting(left: Any, right: Any) -> bool:
    """Whether two values of a setting are the same (numbers to 12 digits)."""
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, int | float) and isinstance(right, int | float):
        return float(left) == float(right) or abs(left - right) <= 1e-12 * max(
            abs(left), abs(right)
        )
    return bool(left == right)


def settings_errors(algorithm: AlgorithmInfo, settings: Mapping[str, Any]) -> list[str]:
    """The errors of a set of settings, one readable line each."""
    try:
        algorithm.settings_model.model_validate(dict(settings))
    except ValidationError as error:
        return [
            f"setting {'.'.join(str(part) for part in item['loc']) or '?'}: "
            f"{str(item['msg']).removeprefix('Value error, ')}"
            for item in error.errors(include_url=False)
        ]
    return []
