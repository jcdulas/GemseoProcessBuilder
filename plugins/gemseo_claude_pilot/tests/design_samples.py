"""Designs on a small grid, for the tests of the physical view (spec § 4.8).

A plate of 6 rows and 8 columns, clamped along its left edge, loaded at the
middle of its right edge, with a notch at the top. Designs are drawn as text,
the top row first: ``#`` solid, ``+`` 0.7, ``:`` 0.3, ``.`` void.
"""

from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any

import numpy as np
from pilot_samples import problem
from pilot_samples import variable

from gemseo_claude_pilot.design import DesignPoint
from gemseo_claude_pilot.design import DesignView
from gemseo_claude_pilot.design import Grid
from gemseo_claude_pilot.design import check_description
from gemseo_claude_pilot.snapshots import Constraint
from gemseo_claude_pilot.snapshots import ProblemSnapshot

ROWS, COLUMNS = 6, 8

BAR = [
    "#.......",
    "#.......",
    "########",
    "#.......",
    "#.......",
    "#.......",
]
"""A bar from the clamped edge to the load: the load path closed."""

LEVELS = {"#": 1.0, "+": 0.7, ":": 0.3, ".": 0.0}


def description(
    rows: int = ROWS, columns: int = COLUMNS, **changes: Any
) -> dict[str, Any]:
    """The physical description of the plate."""
    cells = list(range(rows * columns))
    middle = rows // 2
    data: dict[str, Any] = {
        "summary": "A plate clamped on its left edge, loaded at its right.",
        "grid": {"rows": rows, "columns": columns, "unit": "element width"},
        "variable": "x",
        "variable_cells": cells,
        "constraint_cells": {"g": cells},
        "features": [
            {
                "name": "notch",
                "cells": [(rows - 1) * columns + columns // 2],
                "note": "A notch.",
            }
        ],
        "supports": [
            {
                "name": "clamp",
                "cells": [row * columns for row in range(rows)],
                "blocks": "x and y",
            }
        ],
        "loads": [
            {
                "name": "load",
                "cells": [middle * columns + columns - 1],
                "direction": [0.0, -1.0],
                "magnitude": 1.0,
            }
        ],
        "fields": [
            {"name": "density", "quantity": "physical density", "role": "density"},
            {
                "name": "stress_ratio",
                "quantity": "stress over its limit",
                "role": "stress_ratio",
                "reduce": "max",
            },
            {"name": "strain_energy", "quantity": "strain energy", "role": "energy"},
        ],
        "minimum_member_size": 3.0,
    }
    data.update(changes)
    return data


def plate(rows: int = ROWS, columns: int = COLUMNS) -> ProblemSnapshot:
    """The problem of the plate: ``x`` in [0, 1] and ``g`` on each cell."""
    size = rows * columns
    return problem(
        variables=[variable("x", size, 0.0, 1.0, 1.0)],
        constraints=[Constraint("g", "g", "ineq", size)],
        inequality_tolerance=1e-4,
    )


def drawing(lines: Sequence[str]) -> np.ndarray:
    """A design drawn as text, the top row first, on the grid (row 0 at the bottom)."""
    return np.array([[LEVELS[char] for char in line] for line in reversed(lines)])


def view(
    fields: Mapping[str, np.ndarray],
    rows: int = ROWS,
    columns: int = COLUMNS,
    **changes: Any,
) -> DesignView:
    """A view of the plate with a best point of these fields."""
    checked = check_description(
        description(rows, columns, **changes), plate(rows, columns)
    )
    size = rows * columns
    return DesignView(
        checked,
        Grid(checked),
        np.zeros(size),
        np.ones(size),
        0,
        1e-4,
        {"best": DesignPoint("best", 3, dict(fields))},
    )


def bar_view(lines: Sequence[str] = BAR, **fields: np.ndarray) -> DesignView:
    """A view of a design drawn as text, as its density and design variable."""
    density = drawing(lines)
    return view({"density": density, "design": density, **fields})
