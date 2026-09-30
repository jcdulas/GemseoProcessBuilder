"""The fields of a design as text maps (spec § 4.8).

One character per map cell, row 0 at the bottom, the supports (``S``), the
loads (``F``) and the features (``A``, ``B``…) marked, with a legend.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from gemseo_claude_pilot.design.description import FieldInfo
from gemseo_claude_pilot.snapshots import Array

if TYPE_CHECKING:
    from gemseo_claude_pilot.design.view import DesignPoint
    from gemseo_claude_pilot.design.view import DesignView


LEGENDS: dict[str, str] = {
    "density": "'#' >= 0.9 solid, '+' 0.5 to 0.9, ':' 0.1 to 0.5, '.' < 0.1 void",
    "stress_ratio": "digit d: a ratio from d/10 to (d+1)/10; '!' above 1 (violated)",
    "constraint": "'!' violated, '*' active (within 0.02 of 0), '.' satisfied",
    "principal_sign": "'T' tension, 'C' compression, '~' both in the cell, '.' none",
    "rank": "digit d: in the d-th tenth of the values of the map, 0 lowest; '.' zero",
    "trend": "'^' up by 0.3 or more, '+' up, '.' still (within 0.05), '-' down, "
    "'v' down by 0.3 or more",
}


def text_map(view: "DesignView", point: "DesignPoint", info: FieldInfo) -> str:
    """A field as text: a header, a legend, column numbers, one line per row."""
    grid = view.grid
    values = grid.reduce(point.fields[info.name], info.reduce)
    style: str = info.role
    if style == "design":
        style = "density"
    if style not in LEGENDS:
        style = "rank"
    characters = _characters(values, style, view.tolerance)
    marks = _marks(view)
    for (row, column), mark in marks.items():
        if 0 <= row < grid.map_rows and 0 <= column < grid.map_columns:
            characters[row][column] = mark
    header = [
        f"{info.name}: {info.quantity}"
        + (f" [{info.unit}]" if info.unit and info.unit != "-" else "")
        + f", at {point.label}",
        f"legend: {LEGENDS[style]}; ' ' outside the domain; 'S' support, "
        "'F' load" + _feature_legend(view),
        f"one map cell = {grid.factor} x {grid.factor} cells ({info.reduce}); "
        "row 0 is the bottom",
    ]
    width = len(str(grid.map_rows - 1))
    tens = "".join(
        str(column // 10 % 10) if column % 10 == 0 else " "
        for column in range(grid.map_columns)
    )
    units = "".join(str(column % 10) for column in range(grid.map_columns))
    lines = [" " * (width + 1) + tens, " " * (width + 1) + units]
    for row in range(grid.map_rows - 1, -1, -1):
        lines.append(f"{row:>{width}} " + "".join(characters[row]).rstrip())
    return "\n".join([*header, *lines])


def _characters(values: Array, style: str, tolerance: float) -> list[list[str]]:
    rows, columns = values.shape
    out = [[" "] * columns for _ in range(rows)]
    finite = np.isfinite(values)
    if style == "rank":
        nonzero = finite & (values != 0)
        edges = (
            np.quantile(values[nonzero], np.linspace(0.1, 0.9, 9))
            if nonzero.any()
            else np.zeros(9)
        )
    for row in range(rows):
        for column in range(columns):
            if not finite[row, column]:
                continue
            value = float(values[row, column])
            if style == "density":
                char = (
                    "#"
                    if value >= 0.9
                    else "+"
                    if value >= 0.5
                    else ":"
                    if value >= 0.1
                    else "."
                )
            elif style == "stress_ratio":
                char = "!" if value > 1 + tolerance else str(min(int(value * 10), 9))
            elif style == "constraint":
                char = "!" if value > tolerance else "*" if value >= -0.02 else "."
            elif style == "trend":
                char = (
                    "^"
                    if value >= 0.3
                    else "+"
                    if value > 0.05
                    else "v"
                    if value <= -0.3
                    else "-"
                    if value < -0.05
                    else "."
                )
            elif style == "principal_sign":
                char = (
                    "T"
                    if value > 0.33
                    else "C"
                    if value < -0.33
                    else "~"
                    if value
                    else "."
                )
            else:
                char = (
                    "."
                    if value == 0
                    else str(int(np.searchsorted(edges, value, side="right")))
                )
            out[row][column] = char
    return out


def _marks(view: "DesignView") -> dict[tuple[int, int], str]:
    grid = view.grid
    marks: dict[tuple[int, int], str] = {}

    def mark(cells: Sequence[int], char: str) -> None:
        rows, columns = np.divmod(np.asarray(cells), grid.columns)
        for row, column in zip(
            rows // grid.factor, columns // grid.factor, strict=True
        ):
            marks[int(row), int(column)] = char

    for support in view.description.supports:
        mark(support.cells, "S")
    for load in view.description.loads:
        mark(load.cells, "F")
    for index, feature in enumerate(view.description.features):
        position = grid.position(feature.cells)
        marks[position[0], position[1]] = chr(ord("A") + index % 26)
    return marks


def _feature_legend(view: "DesignView") -> str:
    items = [
        f"'{chr(ord('A') + index % 26)}' {feature.name}"
        for index, feature in enumerate(view.description.features)
    ]
    return ", " + ", ".join(items) if items else ""
