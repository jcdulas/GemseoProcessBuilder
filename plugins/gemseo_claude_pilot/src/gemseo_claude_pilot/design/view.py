"""The design at some points, and what Claude reads of it (spec § 4.8)."""

from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from gemseo_claude_pilot.design.description import DesignError
from gemseo_claude_pilot.design.description import FieldInfo
from gemseo_claude_pilot.design.description import Grid
from gemseo_claude_pilot.design.description import PhysicalDescription
from gemseo_claude_pilot.design.description import rounded
from gemseo_claude_pilot.design.indicators import compare
from gemseo_claude_pilot.design.indicators import indicators
from gemseo_claude_pilot.design.maps import text_map
from gemseo_claude_pilot.snapshots import Array
from gemseo_claude_pilot.snapshots import Entry

STILL = 0.05
"""A normalized move below this is no move, for the trend."""


@dataclass(frozen=True)
class DesignPoint:
    """The fields of the design at one point, on the grid."""

    label: str
    """``best``, ``current``, ``start`` or ``evaluation <n>``."""

    evaluation: int
    """-1 for the starting point before any evaluation."""

    fields: Mapping[str, Array]
    """By name: the model's fields, ``design`` (the design variable normalized
    by its bounds), ``constraint:<name>``, ``price:<name>``, ``stationarity``."""


@dataclass(frozen=True)
class RestartRecord:
    """A restart applied, and the design before and after it."""

    evaluation: int
    """The evaluations made when it was applied."""

    answers: str
    """The physical diagnosis it answers."""

    base: str
    transforms: tuple[Mapping[str, Any], ...]
    before: Mapping[str, Any]
    """The indicators at its base point."""

    started: Mapping[str, Any]
    """The indicators of the design it started from (from the design variable)."""

    map_before: str
    map_after: str


class DesignView:
    """What the advisor needs of the design for one call.

    Args:
        description: The physical description.
        grid: Its grid.
        lower: The lower bounds of the design variable.
        upper: Its upper bounds.
        start: Where the design variable starts in the design vector.
        tolerance: The tolerance of the inequality constraints.
        points: The points prepared, by label.
        restarts: The restarts applied so far.
        constraint_keys: The key of each constraint laid on the grid in the
            database (its standardized name).
    """

    def __init__(
        self,
        description: PhysicalDescription,
        grid: Grid,
        lower: Array,
        upper: Array,
        start: int,
        tolerance: float,
        points: Mapping[str, DesignPoint],
        restarts: Sequence[RestartRecord] = (),
        constraint_keys: Mapping[str, str] | None = None,
    ) -> None:
        self.description = description
        self.grid = grid
        self.lower = lower
        self.upper = upper
        self.start = start
        self.tolerance = tolerance
        self.points = dict(points)
        self.restarts = tuple(restarts)
        self.trend_span = 0
        """The iterates the trend of the current point spans (0: no trend)."""
        self.constraint_keys = dict(constraint_keys or {})

    # The points.

    def point(self, which: str | int, entries: Sequence[Entry] = ()) -> DesignPoint:
        """A prepared point (``best``, ``current``, ``start``), or an evaluation.

        An evaluation has the design variable and the constraints only: the
        model's fields are computed at the prepared points.

        Raises:
            DesignError: When there is no such point.
        """
        if isinstance(which, str) and which in self.points:
            return self.points[which]
        if isinstance(which, int) and 0 <= which < len(entries):
            return entry_point(self, entries[which], which, f"evaluation {which}")
        available = ", ".join([*self.points, "an evaluation index"])
        raise DesignError(f"there is no point {which} (available: {available})")

    def main_point(self) -> DesignPoint | None:
        """The best point, else the current one, else the start."""
        for label in ("best", "current", "start"):
            if label in self.points:
                return self.points[label]
        return None

    # What Claude reads.

    def field_info(self, name: str) -> FieldInfo:
        """The meaning of a field of a point, the model's or the copilot's."""
        for info in self.description.fields:
            if info.name == name:
                return info
        if name == "trend":
            return FieldInfo(
                name=name,
                quantity=f"the move of the design variable over the last "
                f"{self.trend_span} iterates, normalized by its bounds",
                role="trend",
                reading="where the design is heading: toward its upper bound "
                "(solid) or its lower bound (void), or still.",
            )
        if name == "design":
            return FieldInfo(
                name=name,
                quantity=f"the design variable {self.description.variable}, "
                "normalized by its bounds (before any filter of the model)",
                role="design",
                reading="0 at its lower bound, 1 at its upper bound.",
            )
        kind, _, constraint = name.partition(":")
        if kind == "constraint":
            return FieldInfo(
                name=name,
                quantity=f"the constraint {constraint}, standardized",
                role="constraint",
                reduce="max",
                reading="it holds at most 0: above the tolerance it is violated, "
                "near 0 active.",
            )
        if kind == "price":
            return FieldInfo(
                name=name,
                quantity=f"the multiplier of the constraint {constraint}",
                unit="objective per unit of the constraint",
                role="price",
                reduce="max",
                reading="how much the objective would gain if the constraint "
                "were relaxed by one unit there: where the constraint costs "
                "most; 0 where it is not active.",
            )
        if kind == "stationarity":
            return FieldInfo(
                name=name,
                quantity="the projected gradient of the Lagrangian",
                unit="objective per unit of the design variable",
                role="stationarity",
                reduce="max",
                reading="where the KKT residual comes from: large where the "
                "design is not at its optimum yet.",
            )
        raise DesignError(f"there is no field named {name}")

    def fields(self, point: DesignPoint) -> list[str]:
        """The fields of a point."""
        return list(point.fields)

    def density_name(self, point: DesignPoint) -> str:
        """The field giving the material: the model's density, else the design."""
        for name in point.fields:
            if self.field_info(name).role == "density":
                return name
        return "design"

    def stress_name(self, point: DesignPoint) -> str | None:
        """The field giving the stresses: a stress ratio, else a constraint."""
        for name in point.fields:
            if self.field_info(name).role == "stress_ratio":
                return name
        return next(
            (name for name in point.fields if name.startswith("constraint:")), None
        )

    def physics(self) -> dict[str, Any]:
        """The physical problem, the grid and its features, for every call."""
        grid, description = self.grid, self.description
        return {
            "summary": description.summary,
            "grid": {
                "rows": grid.rows,
                "columns": grid.columns,
                "cell_size": description.grid.cell_size,
                "unit": description.grid.unit,
            },
            "maps": (
                f"Maps of {grid.map_rows} rows x {grid.map_columns} columns; one "
                f"map cell is {grid.factor} x {grid.factor} cells of the grid. "
                "Positions are [row, column] in map cells, row 0 at the bottom."
            ),
            "design_variable": description.variable,
            "constraints_on_the_grid": list(description.constraint_cells),
            "minimum_member_size": description.minimum_member_size,
            "features": [
                {"name": item.name, "at": grid.position(item.cells), "note": item.note}
                for item in description.features
            ],
            "supports": [
                {
                    "name": item.name,
                    "extent": grid.extent(item.cells),
                    "blocks": item.blocks,
                }
                for item in description.supports
            ],
            "loads": [
                {
                    "name": item.name,
                    "extent": grid.extent(item.cells),
                    "direction": item.direction,
                    "magnitude": rounded(item.magnitude),
                    "unit": item.unit,
                }
                for item in description.loads
            ],
            "fields": [
                {
                    "name": info.name,
                    "quantity": info.quantity,
                    "unit": info.unit,
                    "reading": info.reading,
                }
                for info in description.fields
            ],
        }

    def detail(self, point: DesignPoint) -> dict[str, Any]:
        """The indicators and the main maps of a point."""
        maps = {}
        density = self.density_name(point)
        maps[density] = self.text_map(density, point)
        stress = self.stress_name(point)
        if stress is not None:
            maps[stress] = self.text_map(stress, point)
        return {
            "point": point.label,
            "evaluation": point.evaluation,
            "indicators": indicators(self, point),
            "maps": maps,
        }

    def context(self, detail: bool) -> dict[str, Any]:
        """The design in the context of a call.

        The physical problem always; with ``detail``, the indicators and the
        main maps of the best point, and where the design is heading: the map
        of its trend and the design it leads to, with its indicators; the
        restarts applied and what they changed.
        """
        section: dict[str, Any] = {
            "physics": self.physics(),
            "points": {label: point.evaluation for label, point in self.points.items()},
        }
        point = self.main_point()
        if point is not None:
            section["fields"] = list(point.fields)
            if detail:
                section["detail"] = self.detail(point)
                heading = self.heading()
                if heading:
                    section["heading"] = heading
        if self.restarts:
            section["restarts"] = self.restarts_now()
        return section

    def heading(self) -> dict[str, Any]:
        """Where the design is heading: its trend, and the design it leads to."""
        current = self.points.get("current")
        anticipated = self.points.get("anticipated")
        if current is None or anticipated is None or "trend" not in current.fields:
            return {}
        trend = current.fields["trend"][self.grid.domain]
        return {
            "over_iterates": self.trend_span,
            "share_toward_upper": rounded(np.mean(trend > STILL)),
            "share_toward_lower": rounded(np.mean(trend < -STILL)),
            "mean_move": rounded(np.mean(np.abs(trend))),
            "trend_map": self.text_map("trend", current),
            "anticipated": {
                "meaning": f"the design if the trend goes on for {self.trend_span} "
                "more iterates (the design variable only, smoothed over half the "
                "minimum member size as the filter of the model does)",
                "indicators": indicators(self, anticipated),
                "map": self.text_map("design", anticipated),
            },
        }

    def restarts_now(self) -> list[dict[str, Any]]:
        """The restarts applied, and what the design is now against before."""
        point = self.main_point()
        now = indicators(self, point) if point is not None else {}
        return [
            {
                "at_evaluation": record.evaluation,
                "answers": record.answers,
                "base": record.base,
                "transforms": [dict(item) for item in record.transforms],
                "before": dict(record.before),
                "started_from": dict(record.started),
                "now": now,
                "changes_since_before": compare(record.before, now),
            }
            for record in self.restarts
        ]

    def text_map(
        self, name: str, point: DesignPoint | str | int, entries: Sequence[Entry] = ()
    ) -> str:
        """The map of a field at a point, with its legend."""
        if not isinstance(point, DesignPoint):
            point = self.point(point, entries)
        if name not in point.fields:
            available = ", ".join(point.fields)
            raise DesignError(
                f"the point {point.label} has no field {name} ({available})"
            )
        info = self.field_info(name)
        return text_map(self, point, info)


def entry_point(view: DesignView, entry: Entry, index: int, label: str) -> DesignPoint:
    """The design variable and the constraints of an evaluation of the database."""
    x, values = entry
    return DesignPoint(
        label, index, entry_fields(view, np.asarray(x, dtype=float), values)
    )


def entry_fields(
    view: DesignView, x: Array, values: Mapping[str, Any]
) -> dict[str, Array]:
    """The design variable, normalized, and the constraints of a point, on the grid."""
    grid = view.grid
    size = grid.cells.size
    design = x[view.start : view.start + size]
    span = np.where(view.upper > view.lower, view.upper - view.lower, 1.0)
    fields = {"design": grid.lay((design - view.lower) / span)}
    for name, cells in view.description.constraint_cells.items():
        value = values.get(view.constraint_keys.get(name, name))
        if value is not None and np.size(value) == len(cells):
            fields[f"constraint:{name}"] = grid.lay(
                np.asarray(value, dtype=float).ravel(), cells
            )
    return fields
