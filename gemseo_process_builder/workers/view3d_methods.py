"""The evaluations of a run that ``nastran_view`` can show (SPEC § 12.2; in the worker).

``gemseo_nastran`` keeps every architecture it sizes in its store: a sizing
folder ``<store>/architectures/<hash>/sizings/<hash>/`` with its manifest
``evaluation.json`` (kind ``sizing``, schema 1). The store of a run is the value
of the input ``store_path`` of its ``gemseo_nastran`` components in the snapshot
of the run, its default store when empty. An evaluation of the run is matched
to the sizing whose parameters equal its design variables: those requested of
its plan (a request the planner adjusted keeps its requested values), or those
of its inputs.
"""

import json
import math
import tempfile
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from gemseo_process_builder.catalog.packages import locate

MANIFEST = "evaluation.json"
DEFAULT_STORE = "gemseo_nastran_store"
"""The default store of ``gemseo_nastran``, in the temporary folder."""

STORE_INPUT = "store_path"
TOLERANCE = 1e-9


@dataclass
class Sizing:
    """A sizing folder of the store and the parameters it was evaluated with."""

    folder: Path
    candidates: list[dict[str, float]] = field(default_factory=list)
    """The sets of parameter values matching it (requested, obtained)."""

    finished: float = 0.0
    """When its manifest was written (the last one wins)."""


def store_of(snapshot: Mapping[str, Any]) -> Path:
    """The store of a run: the input ``store_path`` of its components, else the default.

    Args:
        snapshot: The project of the run (``project.gpb.json``).
    """
    for node in _components(snapshot.get("root", {})):
        config = node.get("config") or {}
        if not str(config.get("module", "")).startswith("gemseo_nastran"):
            continue
        for port in node.get("ports") or []:
            is_store = port.get("local_name") == STORE_INPUT
            if is_store and port.get("direction") == "in" and port.get("default"):
                return Path(str(port["default"]))
        value = (config.get("init_args") or {}).get(STORE_INPUT)
        if value:
            return Path(str(value))
    return Path(tempfile.gettempdir()) / DEFAULT_STORE


def _components(node: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    if node.get("type") == "component":
        yield node
    for child in node.get("children") or []:
        yield from _components(child)


def index(store: Path) -> tuple[list[Sizing], list[str]]:
    """The sizing folders of a store that are done, and what could not be read."""
    sizings: list[Sizing] = []
    problems: list[str] = []
    for path in sorted(store.glob(f"architectures/*/sizings/*/{MANIFEST}")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            sizing = _sizing(path, manifest)
        except (OSError, ValueError, TypeError, AttributeError) as error:
            problems.append(f"{path}: {error}")
            continue
        if sizing is not None:
            sizings.append(sizing)
    return sizings, problems


def _sizing(path: Path, manifest: Mapping[str, Any]) -> Sizing | None:
    """The sizing of a manifest; ``None`` when it is not a sizing done."""
    if manifest.get("schema") != 1:
        msg = f"schema {manifest.get('schema')!r} is not 1"
        raise ValueError(msg)
    if manifest.get("kind") != "sizing" or manifest.get("status") != "done":
        return None
    sizing = Sizing(path.parent, finished=path.stat().st_mtime)
    plan = manifest.get("plan") or {}
    for request in plan.get("requests") or []:
        requested = _numbers(request.get("requested") or {})
        if requested:
            sizing.candidates.append(requested)
        keys = request.get("keys") or {}
        obtained = {
            name: value
            for name, key in keys.items()
            if (value := _number(_at(manifest.get("inputs") or {}, str(key))))
            is not None
        }
        if obtained:
            sizing.candidates.append(obtained)
    inputs = _numbers(manifest.get("inputs") or {})
    if inputs:
        sizing.candidates.append(inputs)
    return sizing


def _at(data: Mapping[str, Any], key: str) -> Any:
    """The value at a dotted key (``fuselage.frames.count``)."""
    value: Any = data
    for part in key.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _numbers(values: Mapping[str, Any]) -> dict[str, float]:
    return {
        str(name): number
        for name, value in values.items()
        if (number := _number(value)) is not None
    }


def match(
    rows: Mapping[int, Mapping[str, float]], sizings: list[Sizing]
) -> dict[int, str]:
    """The sizing folder of each evaluation, by the values of its design variables.

    Args:
        rows: The design variables of each evaluation, by evaluation number.
        sizings: The sizings of the store.
    """
    found: dict[int, str] = {}
    for evaluation, values in rows.items():
        best: Sizing | None = None
        for sizing in sizings:
            if any(_equal(values, candidate) for candidate in sizing.candidates) and (
                best is None or sizing.finished > best.finished
            ):
                best = sizing
        if best is not None:
            found[evaluation] = str(best.folder)
    return found


def _equal(values: Mapping[str, float], candidate: Mapping[str, float]) -> bool:
    return bool(values) and all(
        name in candidate and math.isclose(value, candidate[name], abs_tol=TOLERANCE)
        for name, value in values.items()
    )


def design_rows(folder: Path) -> dict[int, dict[str, float]]:
    """The design variables of each evaluation of a run (scalar variables)."""
    from gemseo_process_builder.results.reader import load

    table = load(folder)
    columns = table.by_role("design variable")
    rows: dict[int, dict[str, float]] = {}
    for row in table.values:
        rows[int(row[0])] = {
            table.columns[position].name: float(row[position]) for position in columns
        }
    return rows


def _state(params: dict[str, Any], context: Any) -> dict[str, Any]:
    """Worker method ``view3d.state``: whether ``nastran_view`` is there, the folders.

    Params:
        folder: The run folder.

    Returns:
        ``available``, ``reason`` when it is not, ``store``, ``folders`` (the sizing
        folder of each evaluation found, by evaluation number) and ``problems``.
    """
    folder = Path(str(params["folder"]))
    available = locate("nastran_view") is not None
    snapshot = json.loads((folder / "project.gpb.json").read_text(encoding="utf-8"))
    store = store_of(snapshot)
    sizings, problems = index(store) if store.is_dir() else ([], [])
    folders = match(design_rows(folder), sizings) if sizings else {}
    return {
        "available": available,
        "reason": ""
        if available
        else "nastran_view is not installed in the Python of the runs.",
        "store": str(store),
        "folders": {str(key): value for key, value in folders.items()},
        "problems": problems,
    }


def register(server: Any) -> None:
    """Add the method of the 3D view to the worker."""
    server.add("view3d.state", _state)
