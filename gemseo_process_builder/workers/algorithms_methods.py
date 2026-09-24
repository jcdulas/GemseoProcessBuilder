"""Algorithms and their settings (runs in the worker; SPEC § 8.6).

GEMSEO 6 describes the settings of its algorithms, MDAs and formulations with
Pydantic models; their JSON schemas drive the forms of the driver editor.
"""

from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError
from pydantic.json_schema import GenerateJsonSchema
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import PydanticOmit
from pydantic_core import core_schema

from gemseo_process_builder.workers.gemseo_loader import require_gemseo
from gemseo_process_builder.workers.server import RequestContext
from gemseo_process_builder.workers.server import WorkerError

KINDS = ("optimization", "doe", "mda", "formulation")

CAPABILITIES = (
    "handle_equality_constraints",
    "handle_inequality_constraints",
    "handle_multiobjective",
    "handle_integer_variables",
    "require_gradient",
)

INTERNAL_MDAS = {"MDASequential"}
"""MDAs only used inside other MDAs."""


class LenientJsonSchema(GenerateJsonSchema):
    """Leave out the fields that have no JSON form (arrays, callables, objects)."""

    def handle_invalid_for_json_schema(
        self, schema: core_schema.CoreSchema, error_info: str
    ) -> JsonSchemaValue:
        """Omit the field instead of failing."""
        raise PydanticOmit

    def callable_schema(self, schema: core_schema.CallableSchema) -> JsonSchemaValue:
        """Omit callables."""
        raise PydanticOmit

    def encode_default(self, dft: Any) -> Any:
        """Replace defaults that cannot be written in JSON by ``None``."""
        try:
            return super().encode_default(dft)
        except Exception:  # Any object can be a default.
            return None


class UnknownAlgorithmError(WorkerError):
    """An algorithm that GEMSEO does not know."""

    def __init__(self, kind: str, name: str) -> None:
        super().__init__("unknown_algorithm", f"No {kind} algorithm named {name}.")


def _algorithm_factory(kind: str) -> Any:
    if kind == "optimization":
        from gemseo.algos.opt.factory import OptimizationLibraryFactory

        return OptimizationLibraryFactory()
    from gemseo.algos.doe.factory import DOELibraryFactory

    return DOELibraryFactory()


def _class_factory(kind: str) -> Any:
    if kind == "mda":
        from gemseo.mda.factory import MDAFactory

        return MDAFactory()
    from gemseo.formulations.factory import MDOFormulationFactory

    return MDOFormulationFactory()


def _first_line(text: str | None) -> str:
    return (text or "").strip().split("\n\n")[0].replace("\n", " ")


def describe(kind: str) -> Iterator[dict[str, Any]]:
    """The algorithms of a kind, with their capabilities."""
    if kind in ("optimization", "doe"):
        factory = _algorithm_factory(kind)
        for name in factory.algorithms:
            library = factory.get_class(factory.algo_names_to_libraries[name])
            info = library.ALGORITHM_INFOS[name]
            yield {
                "name": name,
                "library": info.library_name,
                "description": info.description,
                "website": info.website,
                "capabilities": {
                    key: bool(getattr(info, key, False)) for key in CAPABILITIES
                },
            }
        return
    factory = _class_factory(kind)
    for name in factory.class_names:
        if name in INTERNAL_MDAS:
            continue
        yield {
            "name": name,
            "library": "GEMSEO",
            "description": _first_line(factory.get_class(name).__doc__),
            "website": "",
            "capabilities": {},
        }


def settings_class(kind: str, name: str) -> type[BaseModel]:
    """The Pydantic model of the settings of an algorithm.

    Raises:
        UnknownAlgorithmError: When the algorithm does not exist.
    """
    if kind in ("optimization", "doe"):
        factory = _algorithm_factory(kind)
        library_name = factory.algo_names_to_libraries.get(name)
        if library_name is None:
            raise UnknownAlgorithmError(kind, name)
        settings: type[BaseModel] = (
            factory.get_class(library_name).ALGORITHM_INFOS[name].Settings
        )
        return settings
    factory = _class_factory(kind)
    if name not in factory.class_names:
        raise UnknownAlgorithmError(kind, name)
    return factory.get_class(name).Settings  # type: ignore[no-any-return]


def settings_schema(kind: str, name: str) -> dict[str, Any]:
    """The JSON schema of the settings, without the fields JSON cannot hold."""
    return settings_class(kind, name).model_json_schema(
        schema_generator=LenientJsonSchema
    )


def validate_settings(kind: str, name: str, settings: dict[str, Any]) -> list[Any]:
    """The errors of a set of settings, as ``[{"field", "message"}]``."""
    try:
        settings_class(kind, name).model_validate(settings)
    except ValidationError as error:
        return [
            {
                "field": ".".join(str(part) for part in item["loc"]),
                "message": str(item["msg"]).removeprefix("Value error, "),
            }
            for item in error.errors(include_url=False)
        ]
    return []


def _check_kind(params: dict[str, Any]) -> str:
    kind = str(params.get("kind"))
    if kind not in KINDS:
        raise WorkerError("invalid_params", f"Unknown algorithm kind {kind}.")
    require_gemseo()
    return kind


def _list(params: dict[str, Any], context: RequestContext) -> list[dict[str, Any]]:
    return list(describe(_check_kind(params)))


def _schema(params: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    return settings_schema(_check_kind(params), str(params.get("name")))


def _validate(params: dict[str, Any], context: RequestContext) -> list[Any]:
    kind = _check_kind(params)
    return validate_settings(
        kind, str(params.get("name")), dict(params.get("settings") or {})
    )


def register(server: Any) -> None:
    """Add the algorithm methods to the worker."""
    server.add("algorithms.list", _list)
    server.add("settings.schema", _schema)
    server.add("settings.validate", _validate)
