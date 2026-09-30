"""The physical indicators of a design (spec § 4.8).

Whether solid material carries each load to the supports, the width of the
members against the smallest one the model resolves, the gray and the dead
material, checkerboards, the stress hot spots and the feature each sits at,
where the constraints cost most. Positions are map cells.
"""

from collections.abc import Mapping
from collections.abc import Sequence
from typing import TYPE_CHECKING
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import ndimage
from scipy.spatial import cKDTree

from gemseo_claude_pilot.design.description import Bool2D
from gemseo_claude_pilot.design.description import Grid
from gemseo_claude_pilot.design.description import rounded
from gemseo_claude_pilot.snapshots import Array

if TYPE_CHECKING:
    from gemseo_claude_pilot.design.view import DesignPoint
    from gemseo_claude_pilot.design.view import DesignView


SOLID = 0.5
"""A cell is solid, for the load path and the members, above this density."""

GRAY = (0.1, 0.9)
"""A cell is gray between these densities."""

ACTIVE_RATIO = 0.98
"""A stress ratio above this is active."""

DEAD_ENERGY = 0.01
"""Solid material whose strain energy is below this share of the mean of the
solid carries nothing: it can be removed."""

ZONES = 5
"""The zones of an indicator listed at most, the most important first."""


def indicators(view: "DesignView", point: "DesignPoint") -> dict[str, Any]:
    """The physical indicators of a point (positions in map cells)."""
    grid = view.grid
    density_name = view.density_name(point)
    density = np.nan_to_num(point.fields[density_name], nan=0.0)
    domain = grid.domain
    solid = domain & (density >= SOLID)
    result: dict[str, Any] = {
        "material": _material(density, domain, density_name),
        "load_path": _load_path(view, solid),
        "members": _members(view, solid),
        "checkerboard": _checkerboard(grid, solid, domain),
    }
    energy = next(
        (name for name in point.fields if view.field_info(name).role == "energy"), None
    )
    if energy is not None:
        result["dead_material"] = _dead(grid, solid, point.fields[energy])
    stress = view.stress_name(point)
    if stress is not None:
        result["hot_spots"] = _hot_spots(view, point.fields[stress], stress)
    for name in point.fields:
        role = view.field_info(name).role
        if role in ("price", "stationarity"):
            result[name] = {"largest": _largest(grid, np.abs(point.fields[name]))}
    return result


def _material(density: Array, domain: Bool2D, name: str) -> dict[str, Any]:
    values = density[domain]
    return {
        "from": name,
        "volume_fraction": rounded(values.mean()),
        "solid_share": rounded(np.mean(values >= GRAY[1])),
        "gray_share": rounded(np.mean((values > GRAY[0]) & (values < GRAY[1]))),
        "void_share": rounded(np.mean(values <= GRAY[0])),
    }


def _load_path(view: "DesignView", solid: Bool2D) -> dict[str, Any]:
    """Whether solid material links each load to a support, and the gap if not."""
    grid = view.grid
    labels, count = ndimage.label(solid)
    support_cells = np.concatenate(
        [np.asarray(item.cells) for item in view.description.supports]
        or [np.zeros(0, int)]
    ).astype(np.intp)
    supported = set(np.unique(labels.flat[support_cells])) - {0}
    loads = []
    for load in view.description.loads:
        held = set(np.unique(labels.flat[np.asarray(load.cells)])) - {0}
        entry: dict[str, Any] = {"load": load.name, "connected": bool(held & supported)}
        if not entry["connected"]:
            source = (
                np.isin(labels, list(held)) if held else _cells_mask(grid, load.cells)
            )
            target = (
                np.isin(labels, list(supported))
                if supported
                else _cells_mask(grid, support_cells)
            )
            entry.update(_gap(grid, source, target))
            entry["why"] = (
                "the load is on void"
                if not held
                else "no solid path from the load to a support"
            )
        loads.append(entry)
    floating = [label for label in range(1, count + 1) if label not in supported]
    sizes = ndimage.sum(solid, labels, floating) if floating else np.zeros(0)
    total = max(int(solid.sum()), 1)
    return {
        "loads": loads,
        "solid_parts": int(count),
        "floating_parts": len(floating),
        "floating_share_of_solid": rounded(float(np.sum(sizes)) / total),
    }


def _cells_mask(grid: Grid, cells: Sequence[int] | NDArray[np.intp]) -> Bool2D:
    mask = np.zeros((grid.rows, grid.columns), dtype=bool)
    mask.flat[np.asarray(cells, dtype=np.intp)] = True
    return mask


def _gap(grid: Grid, source: Bool2D, target: Bool2D) -> dict[str, Any]:
    """The shortest distance between two sets of cells, and where."""
    a = np.argwhere(source)
    b = np.argwhere(target)
    if not len(a) or not len(b):
        return {"gap": None}
    distances, nearest = cKDTree(b).query(a)
    index = int(np.argmin(distances))
    start, end = a[index], b[nearest[index]]
    f = grid.factor
    return {
        "gap": rounded(float(distances[index]) - 1.0),
        "gap_unit": "cells of the grid",
        "from": [int(start[0] // f), int(start[1] // f)],
        "to": [int(end[0] // f), int(end[1] // f)],
    }


def _members(view: "DesignView", solid: Bool2D) -> dict[str, Any]:
    """The width of the members along their middle, against the smallest allowed."""
    grid = view.grid
    distance = ndimage.distance_transform_edt(solid)
    ridge = solid & (distance >= ndimage.maximum_filter(distance, size=3))
    widths = 2 * distance[ridge] - 1
    minimum = view.description.minimum_member_size
    result: dict[str, Any] = {
        "minimum_member_size": minimum,
        "median_width": rounded(np.median(widths)) if widths.size else None,
    }
    if minimum and widths.size:
        thin = ridge & (2 * distance - 1 < minimum)
        result["thin_share"] = rounded(np.mean(widths < minimum))
        labels, count = ndimage.label(thin, structure=np.ones((3, 3)))
        zones: list[dict[str, Any]] = []
        for label in range(1, count + 1):
            cells = np.flatnonzero(labels == label)
            zones.append(
                {
                    "at": grid.position(cells),
                    "width": rounded(float(np.min(2 * distance.flat[cells] - 1))),
                    "length": int(cells.size),
                }
            )
        zones.sort(key=lambda zone: -zone["length"])
        result["thin_members"] = zones[:ZONES]
    return result


def _checkerboard(grid: Grid, solid: Bool2D, domain: Bool2D) -> dict[str, Any]:
    """2 x 2 blocks of alternating solid and void cells."""
    a, b = solid[:-1, :-1], solid[:-1, 1:]
    c, d = solid[1:, :-1], solid[1:, 1:]
    inside = domain[:-1, :-1] & domain[:-1, 1:] & domain[1:, :-1] & domain[1:, 1:]
    pattern = inside & (a == d) & (b == c) & (a != b)
    found = np.argwhere(pattern)
    f = grid.factor
    return {
        "blocks": len(found),
        "at": [int(found[0][0] // f), int(found[0][1] // f)] if len(found) else None,
    }


def _dead(grid: Grid, solid: Bool2D, energy: Array) -> dict[str, Any]:
    """Solid material that carries almost nothing."""
    values = np.nan_to_num(energy, nan=0.0)
    if not solid.any():
        return {"share_of_solid": None}
    mean = float(values[solid].mean())
    dead = solid & (values < DEAD_ENERGY * mean)
    labels, count = ndimage.label(dead)
    zones: list[dict[str, Any]] = []
    for label in range(1, count + 1):
        cells = np.flatnonzero(labels == label)
        zones.append({"at": grid.position(cells), "cells": int(cells.size)})
    zones.sort(key=lambda zone: -zone["cells"])
    return {
        "share_of_solid": rounded(float(dead.sum()) / float(solid.sum())),
        "zones": zones[:ZONES],
    }


def _hot_spots(view: "DesignView", values: Array, name: str) -> dict[str, Any]:
    """The zones of active or violated stress, and the feature each sits at."""
    grid = view.grid
    finite = np.nan_to_num(values, nan=-np.inf)
    role = view.field_info(name).role
    if role == "stress_ratio":
        violated = finite > 1 + view.tolerance
        hot = finite >= ACTIVE_RATIO
    else:
        violated = finite > view.tolerance
        hot = finite >= -(1 - ACTIVE_RATIO)
    labels, count = ndimage.label(hot, structure=np.ones((3, 3)))
    features = [
        (item.name, np.argwhere(_cells_mask(grid, item.cells)))
        for item in view.description.features
    ]
    near = 3 * (view.description.minimum_member_size or 1.0)
    zones: list[dict[str, Any]] = []
    for label in range(1, count + 1):
        mask = labels == label
        cells = np.flatnonzero(mask)
        zone: dict[str, Any] = {
            "peak": rounded(float(finite[mask].max())),
            "cells": int(cells.size),
            "violated_cells": int(np.count_nonzero(violated & mask)),
            "at": grid.position(cells),
        }
        points = np.argwhere(mask)
        for feature, located in features:
            if not len(located):
                continue
            distance = float(cKDTree(located).query(points)[0].min())
            if distance <= near:
                zone["at_feature"] = feature
                zone["distance_to_feature"] = rounded(distance)
                break
        zones.append(zone)
    zones.sort(key=lambda zone: -(zone["peak"] or -np.inf))
    return {
        "from": name,
        "violated_cells": int(violated.sum()),
        "active_cells": int(hot.sum()),
        "zones": zones[:ZONES],
    }


def _largest(grid: Grid, values: Array) -> list[dict[str, Any]]:
    """The map cells of the largest values."""
    reduced = grid.reduce(values, "max")
    finite = np.nan_to_num(reduced, nan=-np.inf)
    order = np.argsort(finite, axis=None)[::-1][:ZONES]
    return [
        {
            "at": [int(index // grid.map_columns), int(index % grid.map_columns)],
            "value": rounded(finite.flat[index]),
        }
        for index in order
        if np.isfinite(finite.flat[index]) and finite.flat[index] > 0
    ]


def compare(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """What changed between the indicators of two points."""
    if not before or not after:
        return {}
    changes: dict[str, Any] = {}
    for key in ("volume_fraction", "solid_share", "gray_share"):
        first = before.get("material", {}).get(key)
        last = after.get("material", {}).get(key)
        if first is not None and last is not None:
            changes[key] = rounded(last - first)
    first_hot = before.get("hot_spots", {})
    last_hot = after.get("hot_spots", {})
    if first_hot and last_hot:
        changes["violated_cells"] = [
            first_hot["violated_cells"],
            last_hot["violated_cells"],
        ]
        changes["hot_spot_zones"] = [len(first_hot["zones"]), len(last_hot["zones"])]
    first_path = [
        item["connected"] for item in before.get("load_path", {}).get("loads", [])
    ]
    last_path = [
        item["connected"] for item in after.get("load_path", {}).get("loads", [])
    ]
    if first_path and last_path:
        changes["loads_connected"] = [sum(first_path), sum(last_path)]
    return changes
