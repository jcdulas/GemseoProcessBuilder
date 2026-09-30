"""The transformations of a design a restart applies (spec § 4.8).

On the design variable normalized by its bounds, laid on its grid, in the
order given; positions and sizes in map cells.
"""

import math
from collections.abc import Callable
from collections.abc import Sequence
from typing import Annotated
from typing import Any
from typing import Literal

import numpy as np
from pydantic import Field
from scipy import ndimage

from gemseo_claude_pilot.design.description import Grid
from gemseo_claude_pilot.design.description import Strict
from gemseo_claude_pilot.snapshots import Array


class Binarize(Strict):
    """Every cell to 0 or 1: at or above the threshold, 1."""

    kind: Literal["binarize"] = "binarize"
    threshold: float = Field(default=0.5, gt=0, lt=1)


class Smooth(Strict):
    """The mean of the design over a disk around each cell."""

    kind: Literal["smooth"] = "smooth"
    radius: float = Field(gt=0, description="In map cells.")


class SetRegion(Strict):
    """Fill or empty a region: a rectangle of map cells, or a disk."""

    kind: Literal["set_region"] = "set_region"
    shape: Literal["rectangle", "disk"]
    value: float = Field(ge=0, le=1, description="0 void, 1 solid.")
    rows: tuple[int, int] | None = Field(
        default=None, description="Rectangle: first and last map rows."
    )
    columns: tuple[int, int] | None = Field(
        default=None, description="Rectangle: first and last map columns."
    )
    center: tuple[float, float] | None = Field(
        default=None, description="Disk: [row, column] in map cells."
    )
    radius: float | None = Field(default=None, gt=0, description="Disk, in map cells.")


class Connect(Strict):
    """A bar of material between two map cells."""

    kind: Literal["connect"] = "connect"
    start: tuple[float, float] = Field(description="[row, column] in map cells.")
    end: tuple[float, float] = Field(description="[row, column] in map cells.")
    width: float = Field(gt=0, description="In map cells.")
    value: float = Field(default=1.0, ge=0, le=1)


class Blend(Strict):
    """A mix with the design of a past evaluation."""

    kind: Literal["blend"] = "blend"
    evaluation: int = Field(ge=0)
    weight: float = Field(gt=0, le=1, description="The share of the other design.")


Transform = Annotated[
    Binarize | Smooth | SetRegion | Connect | Blend, Field(discriminator="kind")
]


def transform_errors(
    transforms: Sequence[Any], grid: Grid, evaluations: int
) -> list[str]:
    """Why some transformations cannot apply on a grid; empty when they can."""
    reasons = []
    rows, columns = grid.map_rows, grid.map_columns

    def inside(position: Sequence[float], what: str) -> None:
        row, column = position
        if not (0 <= row < rows and 0 <= column < columns):
            reasons.append(
                f"{what} [{row:g}, {column:g}] is outside the map of {rows} rows "
                f"and {columns} columns"
            )

    for item in transforms:
        if isinstance(item, SetRegion):
            if item.shape == "rectangle":
                if item.rows is None or item.columns is None:
                    reasons.append("a rectangle needs rows and columns")
                    continue
                inside((item.rows[0], item.columns[0]), "the rectangle corner")
                inside((item.rows[1], item.columns[1]), "the rectangle corner")
                if item.rows[0] > item.rows[1] or item.columns[0] > item.columns[1]:
                    reasons.append(
                        "a rectangle goes from its first to its last row and column"
                    )
            elif item.center is None or item.radius is None:
                reasons.append("a disk needs a center and a radius")
            else:
                inside(item.center, "the disk center")
        elif isinstance(item, Connect):
            inside(item.start, "the start of the bar")
            inside(item.end, "the end of the bar")
        elif isinstance(item, Blend) and item.evaluation >= evaluations:
            reasons.append(f"there is no evaluation {item.evaluation} to blend with")
    return reasons


def apply_transforms(
    design: Array,
    transforms: Sequence[Any],
    grid: Grid,
    other: Callable[[int], Array] | None,
) -> Array:
    """The design (normalized, on the grid) after some transformations.

    Args:
        design: The normalized design on the grid (NaN outside the domain).
        transforms: The transformations, in order.
        grid: The grid.
        other: The normalized design of a past evaluation, on the grid.
    """
    values = np.nan_to_num(design, nan=0.0).copy()
    domain = grid.domain
    rows, columns = grid.map_row, grid.map_column
    for item in transforms:
        if isinstance(item, Binarize):
            values = np.where(values >= item.threshold, 1.0, 0.0)
        elif isinstance(item, Smooth):
            radius = item.radius * grid.factor
            size = math.ceil(radius)
            offsets = np.arange(-size, size + 1)
            kernel = (
                offsets[:, None] ** 2 + offsets[None, :] ** 2 <= radius**2
            ).astype(float)
            weights = ndimage.convolve(domain.astype(float), kernel, mode="constant")
            total = ndimage.convolve(values * domain, kernel, mode="constant")
            values = np.where(weights > 0, total / np.maximum(weights, 1e-300), values)
        elif isinstance(item, SetRegion):
            if item.shape == "rectangle":
                assert item.rows is not None and item.columns is not None
                region = (
                    (np.floor(rows) >= item.rows[0])
                    & (np.floor(rows) <= item.rows[1])
                    & (np.floor(columns) >= item.columns[0])
                    & (np.floor(columns) <= item.columns[1])
                )
            else:
                assert item.center is not None and item.radius is not None
                center = np.asarray(item.center) + 0.5
                region = (rows - center[0]) ** 2 + (
                    columns - center[1]
                ) ** 2 <= item.radius**2
            values = np.where(region, item.value, values)
        elif isinstance(item, Connect):
            start = np.asarray(item.start, dtype=float) + 0.5
            end = np.asarray(item.end, dtype=float) + 0.5
            along = end - start
            length = float(along @ along)
            t = (
                np.clip(
                    ((rows - start[0]) * along[0] + (columns - start[1]) * along[1])
                    / length,
                    0,
                    1,
                )
                if length
                else np.zeros_like(rows)
            )
            distance = np.hypot(
                rows - start[0] - t * along[0], columns - start[1] - t * along[1]
            )
            values = np.where(distance <= item.width / 2, item.value, values)
        elif isinstance(item, Blend) and other is not None:
            values = (1 - item.weight) * values + item.weight * np.nan_to_num(
                other(item.evaluation), nan=0.0
            )
    return np.where(domain, np.clip(values, 0.0, 1.0), np.nan)


def transforms_help(grid: Grid) -> dict[str, Any]:
    """What ``list_design_transforms`` answers."""
    return {
        "map": {
            "rows": grid.map_rows,
            "columns": grid.map_columns,
            "cells_per_map_cell": grid.factor,
            "convention": "[row, column] in map cells, row 0 at the bottom",
        },
        "applies_to": "the design variable normalized by its bounds (0 lower, "
        "1 upper), before any filter of the model; in the order given",
        "transforms": {
            "binarize": "{threshold}: cells at or above it to 1, the others to 0",
            "smooth": "{radius}: the mean over a disk of this radius (map cells)",
            "set_region": "{shape: rectangle, rows: [first, last], columns: "
            "[first, last], value} or {shape: disk, center: [row, column], "
            "radius, value}: fill (1) or empty (0) a region",
            "connect": "{start: [row, column], end: [row, column], width, value}: "
            "a bar between two map cells, to close a load path",
            "blend": "{evaluation, weight}: mix with the design of a past evaluation",
        },
    }
