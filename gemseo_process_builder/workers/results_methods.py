"""Reading run results for the application (runs in the worker)."""

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from gemseo_process_builder.results import reader
from gemseo_process_builder.results.reader import Filter
from gemseo_process_builder.results.reader import ResultsError
from gemseo_process_builder.results.reader import Sort
from gemseo_process_builder.workers.server import RequestContext
from gemseo_process_builder.workers.server import WorkerError


def _folder(params: dict[str, Any]) -> Path:
    return Path(str(params.get("folder", "")))


def _query(params: dict[str, Any]) -> tuple[Sort | None, list[Filter]]:
    try:
        sort = Sort.model_validate(params["sort"]) if params.get("sort") else None
        filters = [Filter.model_validate(item) for item in params.get("filters") or []]
    except ValidationError as error:
        raise WorkerError("invalid_params", f"Invalid query: {error}") from None
    return sort, filters


def _reporting(function: Any) -> Any:
    """Report ``ResultsError`` as a worker error the user can read."""

    def method(params: dict[str, Any], context: RequestContext) -> Any:
        try:
            return function(params)
        except ResultsError as error:
            raise WorkerError("results_error", str(error)) from None

    return method


def _rows(params: dict[str, Any]) -> dict[str, Any]:
    sort, filters = _query(params)
    evaluations = params.get("evaluations")
    return reader.rows(
        _folder(params),
        int(params.get("offset", 0)),
        int(params.get("limit", 500)),
        sort,
        filters,
        [int(value) for value in evaluations] if evaluations is not None else None,
    )


def _binned(params: dict[str, Any]) -> dict[str, Any]:
    _, filters = _query(params)
    return reader.binned(
        _folder(params),
        str(params["x"]),
        str(params["y"]),
        int(params.get("bins", 40)),
        filters,
    )


def _matrix(params: dict[str, Any]) -> dict[str, Any]:
    return reader.matrix(
        _folder(params),
        list(params.get("names") or []),
        int(params.get("max_rows", 5000)),
    )


def _export(params: dict[str, Any]) -> int:
    sort, filters = _query(params)
    evaluations = params.get("evaluations")
    return reader.export_csv(
        _folder(params),
        Path(str(params["path"])),
        params.get("names"),
        sort,
        filters,
        [int(value) for value in evaluations] if evaluations is not None else None,
    )


def register(server: Any) -> None:
    """Add the results methods to the worker."""
    server.add("results.summary", _reporting(lambda p: reader.summary(_folder(p))))
    server.add("results.columns", _reporting(lambda p: reader.columns(_folder(p))))
    server.add("results.rows", _reporting(_rows))
    server.add(
        "results.history",
        _reporting(lambda p: reader.history(_folder(p), list(p.get("names") or []))),
    )
    server.add("results.export_csv", _reporting(_export))
    server.add("results.binned", _reporting(_binned))
    server.add("results.matrix", _reporting(_matrix))
