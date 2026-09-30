"""What a model says of the physics of its design, checked; its grid (spec § 4.8).

The protocol :class:`PhysicalDesign` of a discipline, the checked form of its
data :class:`PhysicalDescription`, and the :class:`Grid` the design lies on,
with its maps reduced by blocks.
"""

import math
from collections.abc import Callable
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import Literal
from typing import Protocol
from typing import runtime_checkable

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError

from gemseo_claude_pilot.snapshots import Array
from gemseo_claude_pilot.snapshots import ProblemSnapshot

MAP_SIZE = 40
"""The largest number of rows and columns of a text map."""

Bool2D = NDArray[np.bool_]


Role = Literal[
    "density",
    "stress_ratio",
    "energy",
    "principal_sign",
    "design",
    "constraint",
    "price",
    "stationarity",
    "trend",
    "other",
]
"""What a field is to the copilot: how it is drawn and interpreted."""

Reduce = Literal["mean", "max", "min"]


class DesignError(ValueError):
    """A physical description that does not fit the problem."""


@runtime_checkable
class PhysicalDesign(Protocol):
    """What a discipline gives to describe the physics of its design.

    ``physical_description`` returns plain data, checked by
    :class:`PhysicalDescription`; ``physical_fields`` the fields it declares,
    one value per component of the design variable, at a point given as the
    input data of the discipline.
    """

    def physical_description(self) -> Mapping[str, Any]:
        """The physics of the design."""

    def physical_fields(self, input_data: Mapping[str, Any]) -> Mapping[str, Any]:
        """The physical fields at a point."""


class Strict(BaseModel):
    """Refuses the fields it does not know: a typo must not go unnoticed."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldInfo(Strict):
    """A field of the design and its physical meaning."""

    name: str
    quantity: str
    unit: str = ""
    role: Role = "other"
    reduce: Reduce = "mean"
    reading: str = ""
    """How to read it: its range, thresholds, what high and low mean."""


class GridInfo(Strict):
    """The grid the design lies on, row 0 at the bottom."""

    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    cell_size: float = Field(default=1.0, gt=0)
    unit: str = ""


class Located(Strict):
    """Something at some cells of the grid: a feature, a support, a load."""

    name: str
    cells: list[int] = Field(min_length=1)
    note: str = ""


class Support(Located):
    """Cells held by a support."""

    blocks: str = ""
    """What it blocks (``x and y``)."""


class Load(Located):
    """Cells where a load is applied."""

    direction: list[float] = Field(default_factory=list)
    """Its direction (x to the right, y upwards)."""

    magnitude: float | None = None
    unit: str = ""


class PhysicalDescription(Strict):
    """The physics of a design on a grid (checked form of the protocol's data)."""

    summary: str
    """The physical problem in a few sentences."""

    grid: GridInfo
    variable: str
    """The design variable laid on the grid."""

    variable_cells: list[int]
    """The cell of each of its components, row-major (``row * columns + column``)."""

    constraint_cells: dict[str, list[int]] = Field(default_factory=dict)
    """The cell of each component of the constraints laid on the grid."""

    features: list[Located] = Field(default_factory=list)
    supports: list[Support] = Field(default_factory=list)
    loads: list[Load] = Field(default_factory=list)
    fields: list[FieldInfo] = Field(default_factory=list)
    """The fields ``physical_fields`` computes."""

    minimum_member_size: float | None = None
    """The width, in cells, of the thinnest member the model can resolve."""


def check_description(
    raw: Mapping[str, Any], problem: ProblemSnapshot
) -> PhysicalDescription:
    """The description of a model, checked against the problem.

    Raises:
        DesignError: When it is not valid, or does not fit the problem.
    """
    try:
        description = PhysicalDescription.model_validate(dict(raw))
    except ValidationError as error:
        raise DesignError(f"the physical description is not valid: {error}") from None
    grid = description.grid
    size = grid.rows * grid.columns
    reasons = []
    variable = problem.variable(description.variable)
    cells = description.variable_cells
    if variable is None:
        reasons.append(f"there is no design variable named {description.variable}")
    elif len(cells) != variable.size:
        reasons.append(
            f"{len(cells)} cells for the {variable.size} components of "
            f"{description.variable}"
        )
    if len(set(cells)) != len(cells):
        reasons.append("two components of the design variable share a cell")
    constraints = {constraint.name: constraint for constraint in problem.constraints}
    for name, laid in description.constraint_cells.items():
        constraint = constraints.get(name)
        if constraint is None:
            reasons.append(f"there is no constraint named {name}")
        # GEMSEO knows the size of a vector constraint once it is evaluated.
        elif constraint.size > 1 and len(laid) != constraint.size:
            reasons.append(
                f"{len(laid)} cells for the {constraint.size} components of {name}"
            )
    groups: list[tuple[str, Sequence[int]]] = [
        ("the design variable", cells),
        *(
            (f"the constraint {name}", laid)
            for name, laid in description.constraint_cells.items()
        ),
        *((f"the feature {item.name}", item.cells) for item in description.features),
        *((f"the support {item.name}", item.cells) for item in description.supports),
        *((f"the load {item.name}", item.cells) for item in description.loads),
    ]
    for what, members in groups:
        if any(cell < 0 or cell >= size for cell in members):
            reasons.append(f"{what} has cells outside the grid of {size} cells")
    names = [item.name for item in description.fields]
    if len(set(names)) != len(names):
        reasons.append("two fields share a name")
    if reasons:
        raise DesignError("; ".join(reasons))
    return description


class Grid:
    """The grid of a description, and its maps reduced by blocks.

    Args:
        description: The physical description.
    """

    def __init__(self, description: PhysicalDescription) -> None:
        self.rows = description.grid.rows
        self.columns = description.grid.columns
        self.factor = max(1, math.ceil(max(self.rows, self.columns) / MAP_SIZE))
        """The cells of the grid along each side of a map cell."""

        self.map_rows = math.ceil(self.rows / self.factor)
        self.map_columns = math.ceil(self.columns / self.factor)
        self.cells = np.asarray(description.variable_cells, dtype=np.intp)
        self.domain: Bool2D = np.zeros((self.rows, self.columns), dtype=bool)
        self.domain.flat[self.cells] = True
        rows, columns = np.indices((self.rows, self.columns))
        self.map_row = (rows + 0.5) / self.factor
        """The position of the center of each cell of the grid, in map units."""

        self.map_column = (columns + 0.5) / self.factor

    def lay(self, values: Array, cells: Sequence[int] | None = None) -> Array:
        """Values of some cells on the grid, NaN elsewhere.

        The cells of the design variable by default.
        """
        grid = np.full((self.rows, self.columns), np.nan)
        grid.flat[self.cells if cells is None else np.asarray(cells)] = values
        return grid

    def components(self, grid: Array) -> Array:
        """The values of the grid at the cells of the design variable."""
        return np.asarray(grid.flat[self.cells], dtype=float)

    def reduce(self, grid: Array, how: Reduce = "mean") -> Array:
        """The map of a grid: each map cell reduces its block, NaN when empty."""
        f = self.factor
        padded = np.full((self.map_rows * f, self.map_columns * f), np.nan)
        padded[: self.rows, : self.columns] = grid
        blocks = padded.reshape(self.map_rows, f, self.map_columns, f).swapaxes(1, 2)
        blocks = blocks.reshape(self.map_rows, self.map_columns, f * f)
        reduced = np.full((self.map_rows, self.map_columns), np.nan)
        present = np.isfinite(blocks).any(axis=2)
        reducers: dict[str, Callable[..., Array]] = {
            "mean": np.nanmean,
            "max": np.nanmax,
            "min": np.nanmin,
        }
        reducer = reducers[how]
        reduced[present] = reducer(blocks[present], axis=1)
        return reduced

    def position(self, cells: Sequence[int] | NDArray[np.intp]) -> list[int]:
        """The map cell of the center of some cells of the grid."""
        rows, columns = np.divmod(np.asarray(cells), self.columns)
        return [
            int(np.mean(rows + 0.5) // self.factor),
            int(np.mean(columns + 0.5) // self.factor),
        ]

    def extent(self, cells: Sequence[int]) -> list[list[int]]:
        """The first and last map cells of the box around some cells."""
        rows, columns = np.divmod(np.asarray(cells), self.columns)
        f = self.factor
        return [
            [int(rows.min() // f), int(columns.min() // f)],
            [int(rows.max() // f), int(columns.max() // f)],
        ]


def rounded(value: Any) -> float | None:
    """A number with 4 significant digits, for Claude; ``None`` if not finite."""
    if value is None:
        return None
    number = float(value)
    return float(f"{number:.4g}") if np.isfinite(number) else None
