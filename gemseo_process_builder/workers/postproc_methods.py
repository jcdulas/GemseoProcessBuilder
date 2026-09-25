"""GEMSEO's own post-processings of a finished run (runs in the worker; SPEC § 12.3).

The optimization problem is read back from ``history.h5``, the post-processing
saves its figures in ``postproc/<name>-<timestamp>/`` inside the run folder,
and the page shows them through the ``gpb://run/`` route.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from gemseo_process_builder.results.models import read_info
from gemseo_process_builder.workers.algorithms_methods import LenientJsonSchema
from gemseo_process_builder.workers.gemseo_loader import require_gemseo
from gemseo_process_builder.workers.server import CancelledError
from gemseo_process_builder.workers.server import RequestContext
from gemseo_process_builder.workers.server import WorkerError

HISTORY_FILE = "history.h5"
POSTPROC_FOLDER = "postproc"
SETTINGS_FILE = "settings.json"

OUTPUT_FIELDS = (
    "save",
    "show",
    "file_path",
    "directory_path",
    "file_name",
    "file_extension",
)
"""Settings chosen by the application: where and how the figures are saved."""

HIDDEN = {"Animation", "TopologyView"}
"""Not offered: an animated GIF of another post-processing, and a view that only
makes sense for topology optimization."""

DOE_POSTPROCESSINGS = (
    "BasicHistory",
    "Correlations",
    "ParallelCoordinates",
    "ParetoFront",
    "RadarChart",
    "SOM",
    "ScatterPlotMatrix",
)
"""The post-processings that make sense without an optimization history."""

IMAGE_EXTENSIONS = (".svg", ".png")


def _factory() -> Any:
    require_gemseo()
    from gemseo.post.factory import PostFactory

    return PostFactory()


def _first_line(text: str | None) -> str:
    return (text or "").strip().split("\n\n")[0].replace("\n", " ")


def _is_doe(folder: Path) -> bool:
    """Whether the run used a DOE algorithm, as told by its ``run.json``."""
    info = read_info(folder)
    if info is None or not info.algorithm:
        return False
    from gemseo.algos.doe.factory import DOELibraryFactory

    return info.algorithm in DOELibraryFactory().algorithms


def available(folder: Path) -> list[str]:
    """The post-processings offered for a run, by name."""
    names = [name for name in _factory().class_names if name not in HIDDEN]
    if _is_doe(folder):
        return [name for name in names if name in DOE_POSTPROCESSINGS]
    return names


def settings_schema(name: str) -> dict[str, Any]:
    """The JSON schema of the settings of a post-processing, without the output ones."""
    schema: dict[str, Any] = (
        _factory()
        .get_class(name)
        .Settings.model_json_schema(schema_generator=LenientJsonSchema)
    )
    for field in OUTPUT_FIELDS:
        schema.get("properties", {}).pop(field, None)
    schema["required"] = [
        field for field in schema.get("required", []) if field not in OUTPUT_FIELDS
    ]
    return schema


def describe(folder: Path) -> list[dict[str, Any]]:
    """The post-processings offered for a run, with their descriptions and schemas."""
    factory = _factory()
    return [
        {
            "name": name,
            "description": _first_line(factory.get_class(name).__doc__),
            "schema": settings_schema(name),
        }
        for name in available(folder)
    ]


def results(folder: Path) -> list[dict[str, Any]]:
    """The post-processings already run, the latest first."""
    root = folder / POSTPROC_FOLDER
    if not root.is_dir():
        return []
    found = []
    for output in sorted(root.iterdir(), reverse=True):
        settings_path = output / SETTINGS_FILE
        if not settings_path.is_file():
            continue
        saved = json.loads(settings_path.read_text(encoding="utf-8"))
        found.append(
            {
                "id": output.name,
                "name": saved.get("name", ""),
                "settings": saved.get("settings", {}),
                "created": saved.get("created", ""),
                "files": _images(folder, output),
            }
        )
    return found


def _images(folder: Path, output: Path) -> list[str]:
    """The images of an output folder, relative to the run folder."""
    return [
        path.relative_to(folder).as_posix()
        for path in sorted(output.iterdir())
        if path.suffix.lower() in IMAGE_EXTENSIONS
    ]


def _output_folder(folder: Path, name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = folder / POSTPROC_FOLDER / f"{name}-{stamp}"
    suffix = 1
    while output.exists():
        suffix += 1
        output = folder / POSTPROC_FOLDER / f"{name}-{stamp}-{suffix}"
    return output


def _execute(problem: Any, name: str, output: Path, settings: dict[str, Any]) -> None:
    """Save the figures as SVG, or as PNG when the post-processing cannot."""
    from gemseo import execute_post

    try:
        execute_post(
            problem,
            post_name=name,
            save=True,
            show=False,
            directory_path=output,
            file_extension="svg",
            **settings,
        )
    except ValueError as error:
        if "svg" not in str(error).lower():
            raise
        execute_post(
            problem,
            post_name=name,
            save=True,
            show=False,
            directory_path=output,
            file_extension="png",
            **settings,
        )


def run(
    folder: Path, name: str, settings: dict[str, Any], context: RequestContext
) -> dict[str, Any]:
    """Execute a post-processing on a run and return its result.

    Raises:
        WorkerError: When the post-processing is unknown, its settings are
            invalid, the run has no history or the post-processing fails.
    """
    if name not in available(folder):
        raise WorkerError("invalid_params", f"No post-processing named {name}.")
    history = folder / HISTORY_FILE
    if not history.is_file():
        raise WorkerError("results_error", "The run has no optimization history.")
    try:
        _factory().get_class(name).Settings.model_validate(settings)
    except ValidationError as error:
        raise WorkerError("invalid_params", f"Invalid settings: {error}") from None

    # Figures are only saved: no window may open in the worker.
    import matplotlib

    matplotlib.use("Agg")
    from gemseo.algos.optimization_problem import OptimizationProblem
    from matplotlib import pyplot

    context.check()
    problem = OptimizationProblem.from_hdf(history)
    output = _output_folder(folder, name)
    output.mkdir(parents=True)
    try:
        _execute(problem, name, output, settings)
        context.check()
    except CancelledError:
        shutil.rmtree(output, ignore_errors=True)
        raise
    except Exception as error:  # GEMSEO raises many kinds of errors.
        shutil.rmtree(output, ignore_errors=True)
        raise WorkerError("postproc_error", f"{name} failed: {error}") from None
    finally:
        pyplot.close("all")
    created = datetime.now().isoformat(timespec="seconds")
    (output / SETTINGS_FILE).write_text(
        json.dumps({"name": name, "settings": settings, "created": created}),
        encoding="utf-8",
    )
    return {
        "id": output.name,
        "name": name,
        "settings": settings,
        "created": created,
        "files": _images(folder, output),
    }


def _folder(params: dict[str, Any]) -> Path:
    return Path(str(params.get("folder", "")))


def _list(params: dict[str, Any], context: RequestContext) -> list[dict[str, Any]]:
    return describe(_folder(params))


def _results(params: dict[str, Any], context: RequestContext) -> list[dict[str, Any]]:
    return results(_folder(params))


def _run(params: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    return run(
        _folder(params),
        str(params.get("name")),
        dict(params.get("settings") or {}),
        context,
    )


def register(server: Any) -> None:
    """Add the post-processing methods to the worker."""
    server.add("postproc.list", _list)
    server.add("postproc.results", _results)
    server.add("postproc.run", _run)
