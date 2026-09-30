"""The model describing the design, found on a scenario (spec § 4.8)."""

import logging
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any

import numpy as np

from gemseo_claude_pilot.design.description import DesignError
from gemseo_claude_pilot.design.description import Grid
from gemseo_claude_pilot.design.description import PhysicalDesign
from gemseo_claude_pilot.design.description import check_description
from gemseo_claude_pilot.design.indicators import indicators
from gemseo_claude_pilot.design.maps import text_map
from gemseo_claude_pilot.design.transforms import Smooth
from gemseo_claude_pilot.design.transforms import apply_transforms
from gemseo_claude_pilot.design.view import DesignPoint
from gemseo_claude_pilot.design.view import DesignView
from gemseo_claude_pilot.design.view import RestartRecord
from gemseo_claude_pilot.design.view import entry_fields
from gemseo_claude_pilot.snapshots import Array
from gemseo_claude_pilot.snapshots import Entry
from gemseo_claude_pilot.snapshots import ProblemSnapshot
from gemseo_claude_pilot.snapshots import disciplines_of
from gemseo_claude_pilot.snapshots import history_from_entries

LOGGER = logging.getLogger(__name__)

TREND_ITERATIONS = 5
"""The iterates the trend of the design is measured over."""


class DesignSource:
    """The discipline describing the design, and the points prepared from it.

    Args:
        discipline: The discipline implementing :class:`PhysicalDesign`.
        problem: The problem as the user set it up.

    Raises:
        DesignError: When the description does not fit the problem.
    """

    def __init__(self, discipline: Any, problem: ProblemSnapshot) -> None:
        self.discipline = discipline
        self.description = check_description(discipline.physical_description(), problem)
        self.grid = Grid(self.description)
        start = 0
        for item in problem.variables:
            if item.name == self.description.variable:
                break
            start += item.size
        self.start = start
        variable = problem.variable(self.description.variable)
        assert variable is not None
        self.lower = variable.lower
        self.upper = variable.upper
        self.tolerance = problem.inequality_tolerance
        self.keys = {
            constraint.name: constraint.standardized_name
            for constraint in problem.constraints
        }
        self._best: tuple[int, DesignPoint] | None = None
        self.failed = False

    @classmethod
    def find(cls, scenario: Any, problem: ProblemSnapshot) -> "DesignSource | None":
        """The design source of a scenario, if one of its disciplines describes it."""
        for discipline in disciplines_of(scenario):
            if isinstance(discipline, PhysicalDesign):
                try:
                    return cls(discipline, problem)
                except Exception as error:  # A wrong description turns the view off.
                    LOGGER.warning(
                        "The physical description of %s is not used: %s",
                        getattr(discipline, "name", discipline),
                        error,
                    )
                    return None
        return None

    def empty_view(self, restarts: Sequence[RestartRecord] = ()) -> DesignView:
        """A view without points."""
        return DesignView(
            self.description,
            self.grid,
            self.lower,
            self.upper,
            self.start,
            self.tolerance,
            {},
            restarts,
            self.keys,
        )

    def view(
        self,
        entries: Sequence[Entry],
        problem: ProblemSnapshot,
        live: Any = None,
        restarts: Sequence[RestartRecord] = (),
        start_x: Array | None = None,
        iterates: Sequence[int] = (),
    ) -> DesignView:
        """The design at the best and the current points (in the optimizer's thread).

        The model's fields at the best point are computed again only when it
        changes. The current point is the last iterate; its ``trend`` is its
        move over the last ``TREND_ITERATIONS`` iterates, and the point
        ``anticipated`` the design the trend leads to, as far again.

        Args:
            entries: The database entries.
            problem: The problem as it is now.
            live: The live run of an LSO algorithm, for the multipliers and the
                stationarity at the current point.
            restarts: The restarts applied so far.
            start_x: The starting point, used before any evaluation.
            iterates: The evaluations of the iterates of an optimizer that
                reports them (not its inner evaluations); every evaluation
                otherwise.
        """
        view = self.empty_view(restarts)
        points: dict[str, DesignPoint] = {}
        if not entries:
            if start_x is not None:
                points["start"] = self._point(view, "start", -1, start_x, {})
            view.points = points
            return view
        history = history_from_entries(entries, problem)
        best = history.best_index
        steps = [index for index in iterates if 0 <= index < len(entries)]
        steps = steps or list(range(len(entries)))
        last = steps[-1]
        x_last, values_last = entries[last]
        current = self._point(
            view, "current", last, np.asarray(x_last, float), values_last
        )
        if live is not None:
            current = self._with_live(current, live)
        span = min(TREND_ITERATIONS, len(steps) - 1)
        if span > 0:
            before = entry_fields(
                view, np.asarray(entries[steps[-1 - span]][0], float), {}
            )["design"]
            now = current.fields["design"]
            current = DesignPoint(
                current.label,
                current.evaluation,
                {**current.fields, "trend": now - before},
            )
            view.trend_span = span
            points["anticipated"] = DesignPoint(
                "anticipated", -1, {"design": self._anticipated(view, now, before)}
            )
        points["current"] = current
        if best >= 0:
            if best == last:
                points["best"] = DesignPoint("best", best, current.fields)
            elif self._best is not None and self._best[0] == best:
                points["best"] = self._best[1]
            else:
                x_best, values_best = entries[best]
                points["best"] = self._point(
                    view, "best", best, np.asarray(x_best, float), values_best
                )
            self._best = (best, points["best"])
        view.points = points
        return view

    def _anticipated(self, view: DesignView, now: Array, before: Array) -> Array:
        """The design the trend leads to, as far again, smoothed.

        Over half the minimum member size, as the filter of a model does:
        extrapolated raw, the design variable showed floating parts and
        checkerboards the model filters out, and Claude could not trust it.
        """
        extrapolated = np.clip(2 * now - before, 0.0, 1.0)
        size = self.description.minimum_member_size or 2.0
        radius = 0.5 * size / self.grid.factor
        return apply_transforms(extrapolated, [Smooth(radius=radius)], self.grid, None)

    def _point(
        self,
        view: DesignView,
        label: str,
        evaluation: int,
        x: Array,
        values: Mapping[str, Any],
    ) -> DesignPoint:
        fields = entry_fields(view, x, values)
        fields.update(self._model_fields(x))
        return DesignPoint(label, evaluation, fields)

    def _model_fields(self, x: Array) -> dict[str, Array]:
        """The model's fields at a point; none if it fails (the run goes on)."""
        if self.failed:
            return {}
        grid = self.grid
        size = grid.cells.size
        defaults = getattr(self.discipline.io.input_grammar, "defaults", {}) or {}
        input_data = {name: np.asarray(value) for name, value in dict(defaults).items()}
        input_data[self.description.variable] = x[self.start : self.start + size]
        try:
            raw = self.discipline.physical_fields(input_data)
            fields = {}
            for info in self.description.fields:
                values = np.asarray(raw[info.name], dtype=float).ravel()
                if values.size != size:
                    raise DesignError(
                        f"the field {info.name} has {values.size} values, not {size}"
                    )
                fields[info.name] = grid.lay(values)
        except Exception as error:  # The fields are a help, never a failure of the run.
            LOGGER.warning("The physical fields of the design are not used: %s", error)
            self.failed = True
            return {}
        return fields

    def _with_live(self, point: DesignPoint, live: Any) -> DesignPoint:
        """The point with the multipliers and stationarity of an LSO algorithm."""
        fields = dict(point.fields)
        grid = self.grid
        by_key = {key: name for name, key in self.keys.items()}
        try:
            for key, values in live.multipliers().items():
                name = by_key.get(key)
                cells = self.description.constraint_cells.get(name or "")
                if cells is not None and len(values) == len(cells):
                    fields[f"price:{name}"] = grid.lay(np.asarray(values, float), cells)
            stationarity = live.stationarity().get(self.description.variable)
            if stationarity is not None and len(stationarity) == grid.cells.size:
                fields["stationarity"] = grid.lay(np.asarray(stationarity, float))
        except Exception as error:  # A help: the view goes on without them.
            LOGGER.warning("The multipliers of the optimizer are not used: %s", error)
        return DesignPoint(point.label, point.evaluation, fields)

    def restart(
        self,
        view: DesignView,
        base: str | int,
        transforms: Sequence[Any],
        entries: Sequence[Entry],
        evaluation: int,
        answers: str,
    ) -> tuple[Array, RestartRecord]:
        """The design variable to restart from, and the record of the restart.

        Args:
            view: The view of the design now.
            base: ``best``, ``current``, or an evaluation.
            transforms: The transformations, in order.
            entries: The database entries.
            evaluation: The evaluations made so far.
            answers: The physical diagnosis the restart answers.
        """
        point = view.point(base, entries)
        grid = self.grid
        design = self._transformed(view, point.fields["design"], transforms, entries)
        span = np.where(self.upper > self.lower, self.upper - self.lower, 1.0)
        value = self.lower + grid.components(design) * span
        started = DesignPoint("restart", evaluation, {"design": design})
        info = view.field_info("design")
        record = RestartRecord(
            evaluation=evaluation,
            answers=answers,
            base=point.label,
            transforms=tuple(item.model_dump(mode="json") for item in transforms),
            before=indicators(view, point),
            started=indicators(view, started),
            map_before=text_map(view, point, view.field_info(view.density_name(point))),
            map_after=text_map(view, started, info),
        )
        return np.clip(value, self.lower, self.upper), record

    def transform(
        self,
        view: DesignView,
        x: Array,
        transforms: Sequence[Any],
        entries: Sequence[Entry],
    ) -> Array:
        """A design vector whose design variable is transformed on its grid."""
        grid = self.grid
        size = grid.cells.size
        span = np.where(self.upper > self.lower, self.upper - self.lower, 1.0)
        variable = x[self.start : self.start + size]
        design = grid.lay((variable - self.lower) / span)
        design = self._transformed(view, design, transforms, entries)
        moved = np.array(x, dtype=float)
        moved[self.start : self.start + size] = np.clip(
            self.lower + grid.components(design) * span, self.lower, self.upper
        )
        return moved

    def _transformed(
        self,
        view: DesignView,
        design: Array,
        transforms: Sequence[Any],
        entries: Sequence[Entry],
    ) -> Array:
        def other(index: int) -> Array:
            return view.point(index, entries).fields["design"]

        return apply_transforms(design, transforms, self.grid, other)
