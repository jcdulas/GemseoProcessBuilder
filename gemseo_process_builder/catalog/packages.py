"""Catalog entries declared by installed packages (SPEC § 7.6; runs in the worker).

A distribution declares an entry point of the group
``gemseo_process_builder.components`` pointing to a list of plain dictionaries,
or to a function returning one, without depending on the application:

.. code-block:: toml

    [project.entry-points."gemseo_process_builder.components"]
    gemseo-nastran = "gemseo_nastran.catalog:COMPONENTS"

Listing the distributions imports nothing. A distribution whose name and
version the catalog cache holds (and, for an editable install, the
modification time of its declaration file) is not loaded again. Otherwise its
declaration is loaded and checked, and the module of each entry is located
without being imported: the modules of the components are imported only when a
component is placed or introspected.
"""

import importlib
import json
import sys
import traceback
from collections.abc import Iterable
from importlib.machinery import ModuleSpec
from importlib.metadata import Distribution
from importlib.metadata import EntryPoint
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from gemseo_process_builder.catalog.models import CatalogEntry
from gemseo_process_builder.catalog.models import PackageScan
from gemseo_process_builder.catalog.models import ScanError
from gemseo_process_builder.catalog.models import normalized_name

GROUP = "gemseo_process_builder.components"
"""The entry-point group of the catalog entries."""

SCHEMA = 1
"""The version of the format of an entry this application reads."""

KINDS = ("python_class", "python_function")

KEYS: dict[str, type] = {
    "kind": str,
    "module": str,
    "attribute": str,
    "group": str,
    "description": str,
    "units": dict,
    "icon": str,
    "schema": int,
}
"""The keys of an entry and their types."""

REQUIRED = ("kind", "module", "attribute")


class Declared:
    """The entry points of one distribution in the group."""

    def __init__(self, distribution: Distribution | None, name: str) -> None:
        self.distribution = distribution
        self.name = name
        self.version = distribution.version if distribution is not None else ""
        self.entry_points: list[EntryPoint] = []

    def stamp(self) -> float | None:
        """The modification time of its declaration files, for an editable install.

        PEP 610: an editable install records ``dir_info.editable`` in its
        ``direct_url.json``; its files change without its version.
        """
        if self.distribution is None:
            return None
        text = self.distribution.read_text("direct_url.json")
        try:
            info = json.loads(text or "{}").get("dir_info", {})
            editable = bool(info.get("editable"))
        except (ValueError, AttributeError):
            return None
        if not editable:
            return None
        times = []
        for entry_point in self.entry_points:
            spec = locate(entry_point.module)
            if spec is not None and spec.origin and Path(spec.origin).is_file():
                times.append(Path(spec.origin).stat().st_mtime)
        return max(times) if times else None


def declarations() -> dict[str, Declared]:
    """The distributions declaring catalog entries, by normalized name.

    Nothing is imported: the metadata of the distributions are read.
    """
    importlib.invalidate_caches()  # Distributions installed since the last call.
    found: dict[str, Declared] = {}
    for entry_point in entry_points(group=GROUP):
        distribution = entry_point.dist
        name = distribution.name if distribution is not None else entry_point.name
        key = normalized_name(name)
        if key not in found:
            found[key] = Declared(distribution, name)
        found[key].entry_points.append(entry_point)
    return dict(sorted(found.items()))


def locate(name: str) -> ModuleSpec | None:
    """Where a dotted module is, without importing it or its parent packages.

    ``importlib.util.find_spec`` imports the parent packages: their ``__init__``
    may be heavy. The finders of ``sys.meta_path`` are asked for each segment
    instead, the parents already imported giving their own locations.
    """
    parts = name.split(".")
    if not all(part.isidentifier() for part in parts):
        return None
    locations: Iterable[str] | None = None
    spec: ModuleSpec | None = None
    for index in range(len(parts)):
        current = ".".join(parts[: index + 1])
        module = sys.modules.get(current)
        spec = getattr(module, "__spec__", None) if module is not None else None
        if spec is None:
            spec = _find(current, locations)
        if spec is None:
            return None
        locations = spec.submodule_search_locations
        if locations is None and index < len(parts) - 1:
            return None  # A module, not a package: it has no submodule.
    return spec


def _find(name: str, locations: Iterable[str] | None) -> ModuleSpec | None:
    for finder in sys.meta_path:
        find_spec = getattr(finder, "find_spec", None)
        if find_spec is None:
            continue
        try:
            spec = find_spec(name, None if locations is None else list(locations))
        except (ImportError, ValueError):
            continue
        if spec is not None:
            return spec  # type: ignore[no-any-return]
    return None


def check_entry(
    item: Any, where: str
) -> tuple[CatalogEntry | None, list[str], list[str]]:
    """An entry of a declaration, with its errors and warnings.

    Args:
        item: The dictionary of the entry.
        where: How the errors name the entry.

    Returns:
        The entry (``None`` when it has errors), its errors and its warnings.
    """
    if not isinstance(item, dict):
        return None, [f"{where} is a {type(item).__name__}, not a dictionary."], []
    errors: list[str] = []
    warnings: list[str] = []
    for key in REQUIRED:
        if key not in item:
            errors.append(f"{where} has no {key}.")
    for key, value in item.items():
        expected = KEYS.get(key)
        if expected is None:
            warnings.append(f"{where}: the key {key!r} is unknown and was ignored.")
        elif not isinstance(value, expected) or isinstance(value, bool):
            errors.append(
                f"{where}: {key} is a {type(value).__name__}, "
                f"not a {expected.__name__}."
            )
    if errors:
        return None, errors, warnings
    if item["kind"] not in KINDS:
        kinds = ", ".join(KINDS)
        errors.append(f"{where}: kind {item['kind']!r} is not one of {kinds}.")
    if not item["attribute"].isidentifier():
        errors.append(f"{where}: {item['attribute']!r} is not a Python name.")
    units = item.get("units", {})
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in units.items()):
        errors.append(f"{where}: units must map names to unit texts.")
    schema = item.get("schema", SCHEMA)
    if schema > SCHEMA:
        warnings.append(
            f"{where} is written in version {schema} of the format; "
            f"the keys of version {SCHEMA} were read."
        )
    if not errors and locate(item["module"]) is None:
        errors.append(f"{where}: the module {item['module']} cannot be found.")
    if errors:
        return None, errors, warnings
    entry = CatalogEntry(
        kind=item["kind"],
        name=item["attribute"],
        module_path="",
        module=item["module"],
        attribute=item["attribute"],
        description=item.get("description", ""),
        group=item.get("group", ""),
        metadata={"units": dict(units), "icon": item.get("icon", "")},
    )
    return entry, [], warnings


def scan_package(declared: Declared, stamp: float | None) -> PackageScan:
    """Load and check the declarations of a distribution.

    A declaration module imported before is executed again: its file may have
    changed (an editable install, a new version).
    """
    scan = PackageScan(name=declared.name, version=declared.version, stamp=stamp)
    for entry_point in declared.entry_points:
        sys.modules.pop(entry_point.module, None)
        try:
            items = entry_point.load()
            if callable(items):
                items = items()
            if not isinstance(items, (list, tuple)):
                msg = (
                    f"{entry_point.value} is a {type(items).__name__}, "
                    "not a list of dictionaries."
                )
                raise TypeError(msg)
        except BaseException as error:  # Package code may raise anything.
            scan.errors.append(
                ScanError(
                    path=entry_point.value,
                    message=f"{type(error).__name__}: {error}",
                    traceback="".join(traceback.format_exception(error)),
                )
            )
            continue
        for index, item in enumerate(items):
            where = f"Entry {index + 1} of {entry_point.value}"
            if isinstance(item, dict) and isinstance(item.get("attribute"), str):
                where = f"{where} ({item['attribute']})"
            entry, errors, warnings = check_entry(item, where)
            scan.warnings.extend(warnings)
            scan.errors.extend(
                ScanError(path=entry_point.value, message=message) for message in errors
            )
            if entry is not None:
                scan.entries.append(entry)
    return scan


_DECLARED: dict[str, PackageScan] | None = None
"""The packages loaded for introspection and the script reader, by normalized
name; loaded again after a scan of the catalog."""


def declared_packages() -> dict[str, PackageScan]:
    """The catalog entries of the installed packages, loaded once per scan."""
    global _DECLARED
    if _DECLARED is None:
        _DECLARED = {}
        for key, declared in declarations().items():
            _DECLARED[key] = scan_package(declared, None)
    return _DECLARED


def declared_entry(module: str, attribute: str) -> CatalogEntry | None:
    """The declaration of an entry of an installed package, if any."""
    for package in declared_packages().values():
        for entry in package.entries:
            if entry.module == module and entry.attribute == attribute:
                return entry
    return None


def package_of(module: str) -> dict[str, str] | None:
    """The installed package declaring catalog entries a module belongs to.

    A module belongs to a package when its top-level package is that of the
    module of one of its entries.
    """
    top = module.split(".")[0]
    for package in declared_packages().values():
        if any(entry.module.split(".")[0] == top for entry in package.entries):
            return {"name": package.name, "version": package.version}
    return None


def _packages(params: dict[str, Any], context: Any) -> list[dict[str, Any]]:
    """Worker method ``catalog.packages``: the packages declaring catalog entries.

    Params:
        known: The packages of the catalog cache: ``name``, ``version`` and
            ``stamp``.
        force: Load every package again (**Refresh**).

    Returns:
        A scan per package, or ``{name, version, stamp, unchanged: true}`` for a
        package of the cache that did not change.
    """
    global _DECLARED
    known = {
        normalized_name(str(item["name"])): (item.get("version"), item.get("stamp"))
        for item in params.get("known", [])
    }
    force = bool(params.get("force"))
    results: list[dict[str, Any]] = []
    for key, declared in declarations().items():
        context.check()
        stamp = declared.stamp()
        if not force and known.get(key) == (declared.version, stamp):
            results.append(
                {
                    "name": declared.name,
                    "version": declared.version,
                    "stamp": stamp,
                    "unchanged": True,
                }
            )
            continue
        results.append(scan_package(declared, stamp).model_dump(mode="json"))
    _DECLARED = None
    return results


def register(server: Any) -> None:
    """Add the method of the installed packages to the worker."""
    server.add("catalog.packages", _packages)
