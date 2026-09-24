"""Discovery of components in Python files (runs in the worker).

A catalog folder may contain:

- Python modules defining ``Discipline`` subclasses (classes imported from
  elsewhere are ignored);
- Python modules defining functions decorated with
  ``gemseo_process_builder.runtime.component``;
- executable wrapper descriptors (``*.gpbwrap.json``).

Each module is imported under a unique name, with its folder temporarily added
to ``sys.path`` so that it can import its sibling modules. An import error is
reported for that file only.
"""

import hashlib
import importlib.util
import inspect
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any

from gemseo_process_builder.catalog.models import CatalogEntry
from gemseo_process_builder.catalog.models import FileScan
from gemseo_process_builder.catalog.models import ScanError
from gemseo_process_builder.runtime.decorators import COMPONENT_ATTRIBUTE

DESCRIPTOR_SUFFIX = ".gpbwrap.json"
IGNORED_FOLDERS = {"__pycache__", ".git", ".venv", "venv", "node_modules"}


def is_ignored(relative: Path) -> bool:
    """Whether a path inside a catalog folder is skipped (caches, hidden files)."""
    return any(
        part in IGNORED_FOLDERS or part.startswith(".") for part in relative.parts
    )


def catalog_files(folder: Path) -> list[Path]:
    """List the files of a catalog folder that may hold components."""
    files = []
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if is_ignored(relative):
            continue
        if path.is_file() and (
            path.suffix == ".py" or path.name.endswith(DESCRIPTOR_SUFFIX)
        ):
            files.append(path)
    return files


def import_file(path: Path) -> ModuleType:
    """Import a Python file under a unique module name."""
    digest = hashlib.sha1(f"{path}:{path.stat().st_mtime}".encode()).hexdigest()[:12]
    name = f"gpb_catalog_{path.stem}_{digest}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        msg = f"{path} cannot be imported."
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    folder = str(path.parent)
    sys.path.insert(0, folder)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    finally:
        if folder in sys.path:
            sys.path.remove(folder)
    return module


def _first_line(text: str | None) -> str:
    return (text or "").strip().splitlines()[0] if (text or "").strip() else ""


def module_entries(module: ModuleType, path: Path) -> list[CatalogEntry]:
    """The components defined in an imported module."""
    from gemseo.core.discipline import Discipline

    entries = []
    for name, member in inspect.getmembers(module):
        if getattr(member, "__module__", None) != module.__name__:
            continue
        if inspect.isclass(member) and issubclass(member, Discipline):
            entries.append(
                CatalogEntry(
                    kind="python_class",
                    name=name,
                    module_path=str(path),
                    attribute=name,
                    description=_first_line(member.__doc__),
                    metadata={"abstract": inspect.isabstract(member)},
                )
            )
        elif inspect.isfunction(member) and hasattr(member, COMPONENT_ATTRIBUTE):
            marker: dict[str, Any] = getattr(member, COMPONENT_ATTRIBUTE)
            entries.append(
                CatalogEntry(
                    kind="python_function",
                    name=name,
                    module_path=str(path),
                    attribute=name,
                    description=marker.get("description")
                    or _first_line(member.__doc__),
                    metadata={
                        "units": marker.get("units", {}),
                        "icon": marker.get("icon", ""),
                    },
                )
            )
    return entries


def scan_file(path: Path) -> FileScan:
    """Scan one file; errors are reported in the result, never raised."""
    result = FileScan(path=str(path), mtime=path.stat().st_mtime)
    if path.name.endswith(DESCRIPTOR_SUFFIX):
        name = path.name[: -len(DESCRIPTOR_SUFFIX)]
        result.entries = [
            CatalogEntry(kind="executable", name=name, module_path=str(path))
        ]
        return result
    try:
        module = import_file(path)
        result.entries = module_entries(module, path)
    except BaseException as error:  # User code may raise anything, even SystemExit.
        result.error = ScanError(
            path=str(path),
            message=f"{type(error).__name__}: {error}",
            traceback="".join(traceback.format_exception(error)),
        )
    return result


def _scan(params: dict[str, Any], context: Any) -> list[dict[str, Any]]:
    """Worker method ``catalog.scan``: scan the given files."""
    from gemseo_process_builder.workers.gemseo_loader import require_gemseo

    require_gemseo()
    results = []
    for file in params.get("files", []):
        context.check()
        path = Path(file)
        if path.exists():
            results.append(scan_file(path).model_dump(mode="json"))
    return results


def register(server: Any) -> None:
    """Add the catalog methods to the worker."""
    server.add("catalog.scan", _scan)
