"""Which variables matter: ranking the columns of a run (runs in the worker).

A run can have hundreds of thousands of design variables and many responses:
no chart can show them all. The views show the variables that matter for a
response, ranked by one of three measures (SPEC § 12.2):

- ``sensitivity``: the correlation between each variable and the response
  over the evaluations, or between its squared distance to its mean and the
  response: a response shaped like a bowl has no linear correlation;
- ``gradient``: the gradient of the response at the best evaluation, read in
  ``history.h5``, times the range of each variable (the change of the response
  when the variable crosses its range);
- ``active``: the active set at the best evaluation: the variables at one of
  their bounds, the constraints at their limit or violated.
"""

from pathlib import Path
from typing import Any
from typing import Literal

import numpy as np

from gemseo_process_builder.results.reader import EQUALITY_TOLERANCE
from gemseo_process_builder.results.reader import INEQUALITY_TOLERANCE
from gemseo_process_builder.results.reader import ResultsError
from gemseo_process_builder.results.reader import RunTable
from gemseo_process_builder.results.reader import best_position
from gemseo_process_builder.results.reader import load

Method = Literal["sensitivity", "gradient", "active"]

INPUT_ROLES = ("design variable",)
RESPONSE_ROLES = ("objective", "constraint", "observable", "output")

MAX_ROWS = 5000
"""The correlations use at most this number of evenly spaced evaluations."""

CHUNK = 4096
"""Columns correlated at once, to bound the memory used."""

BOUND_TOLERANCE = 1e-6
"""A variable closer to a bound than this share of its range is at the bound."""

ACTIVE_SHARE = 1e-3
"""An inequality constraint within this share of its values' range of zero is active."""


def column_bounds(
    table: RunTable, positions: list[int]
) -> tuple[np.ndarray, np.ndarray]:
    """The lower and upper bounds of the columns (NaN where unknown)."""
    by_variable = {v.name: v for v in table.info.variables}
    lower = np.full(len(positions), np.nan)
    upper = np.full(len(positions), np.nan)
    for index, position in enumerate(positions):
        column = table.columns[position]
        variable = by_variable.get(column.variable)
        if variable is None or column.component >= len(variable.lower):
            continue
        low = variable.lower[column.component]
        high = variable.upper[column.component]
        lower[index] = np.nan if low is None else low
        upper[index] = np.nan if high is None else high
    return lower, upper


def _ranges(table: RunTable, positions: list[int]) -> np.ndarray:
    """The width of the bounds, or of the values when a bound is missing."""
    lower, upper = column_bounds(table, positions)
    width: np.ndarray = upper - lower
    missing = ~np.isfinite(width)
    if missing.any():
        values = table.values[:, np.asarray(positions)[missing]]
        with np.errstate(invalid="ignore"):
            width[missing] = np.nanmax(values, axis=0) - np.nanmin(values, axis=0)
    width[~np.isfinite(width) | (width == 0)] = 1.0
    return width


def _pearson(target: np.ndarray, chunk: np.ndarray) -> np.ndarray:
    """The absolute correlation of each column with a standardized target."""
    spread = chunk.std(axis=0)
    centered = chunk - chunk.mean(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        values = np.abs(target @ centered / (len(target) * spread))
    finite: np.ndarray = np.nan_to_num(values)
    return finite


def _correlations(table: RunTable, positions: list[int], response: int) -> np.ndarray:
    """How much the response follows each column, linearly or quadratically."""
    rows = np.arange(len(table.values))
    if len(rows) > MAX_ROWS:
        rows = np.unique(np.linspace(0, len(rows) - 1, MAX_ROWS).round().astype(int))
    target = table.values[rows, response]
    known = np.isfinite(target)
    rows, target = rows[known], target[known]
    scores = np.zeros(len(positions))
    if len(rows) < 3 or np.std(target) == 0:
        return scores
    target = (target - target.mean()) / target.std()
    for start in range(0, len(positions), CHUNK):
        chunk = table.values[np.ix_(rows, positions[start : start + CHUNK])]
        chunk = np.where(np.isfinite(chunk), chunk, np.nanmean(chunk, axis=0))
        linear = _pearson(target, chunk)
        quadratic = _pearson(target, (chunk - chunk.mean(axis=0)) ** 2)
        scores[start : start + CHUNK] = np.maximum(linear, quadratic)
    return scores


def _gradient(
    folder: Path, table: RunTable, response: int, best: int
) -> tuple[np.ndarray, int]:
    """The gradient of the response, and the evaluation it was read at.

    The gradient at the best evaluation, or at the last one with a gradient. It
    has one value per design variable column, in the order of the columns.
    """
    from gemseo.algos.database import Database

    path = folder / "history.h5"
    column = table.columns[response]
    if not path.exists():
        msg = "The run has no history: rank by sensitivity instead."
        raise ResultsError(msg)
    database = Database.from_hdf(path)
    key = database.get_gradient_name(column.variable)
    found: tuple[np.ndarray, int] | None = None
    for index, (_, values) in enumerate(database.items()):
        gradient = values.get(key)
        if gradient is not None:
            found = (np.atleast_2d(np.asarray(gradient, float)), index)
            if index == best:
                break
    if found is None:
        msg = (
            f"The run has no gradients of {column.variable}: "
            "rank by sensitivity instead."
        )
        raise ResultsError(msg)
    gradient, index = found
    return gradient[min(column.component, len(gradient) - 1)], index


def _at_bounds(
    table: RunTable, positions: list[int], best: int
) -> tuple[np.ndarray, list[str | None]]:
    """How close each variable is to a bound (1 at the bound), and which one."""
    lower, upper = column_bounds(table, positions)
    values = table.values[best, positions]
    width = upper - lower
    with np.errstate(invalid="ignore", divide="ignore"):
        to_lower = (values - lower) / width
        to_upper = (upper - values) / width
    distance = np.nan_to_num(np.fmin(to_lower, to_upper), nan=1.0)
    bounds: list[str | None] = [None] * len(positions)
    for index in np.flatnonzero(distance <= BOUND_TOLERANCE):
        bounds[index] = "lower" if to_lower[index] <= to_upper[index] else "upper"
    return 1.0 - np.clip(distance, 0.0, 1.0), bounds


def _status(table: RunTable, position: int, best: int) -> str | None:
    """Whether a constraint is violated, active or satisfied at the best point."""
    column = table.columns[position]
    if column.role != "constraint":
        return None
    kinds = {v.name: v.constraint_type for v in table.info.variables}
    value = table.values[best, position]
    if not np.isfinite(value):
        return None
    if kinds.get(column.variable) == "eq":
        return "violated" if abs(value) > EQUALITY_TOLERANCE else "active"
    if value > INEQUALITY_TOLERANCE:
        return "violated"
    values = table.values[:, position]
    spread = np.nanmax(np.abs(values)) if np.isfinite(values).any() else 0.0
    return (
        "active"
        if abs(value) <= max(INEQUALITY_TOLERANCE, ACTIVE_SHARE * spread)
        else "satisfied"
    )


STATUS_ORDER = {"violated": 0, "active": 1, "satisfied": 2, None: 3}
ROLE_ORDER = {role: index for index, role in enumerate(RESPONSE_ROLES)}


def _responses(table: RunTable, best: int, active_only: bool) -> list[dict[str, Any]]:
    """The responses with their value and status at the best evaluation.

    The objective first, then the violated and active constraints (the most
    violated first), then the others.
    """
    found: list[dict[str, Any]] = []
    for position in table.by_role(*RESPONSE_ROLES):
        column = table.columns[position]
        status = _status(table, position, best)
        if (
            active_only
            and status in ("satisfied", None)
            and column.role == "constraint"
        ):
            continue
        value = float(table.values[best, position])
        found.append(
            {
                "name": column.name,
                "role": column.role,
                "value": value if np.isfinite(value) else None,
                "status": status,
            }
        )
    found.sort(
        key=lambda item: (
            item["role"] != "objective",
            STATUS_ORDER[item["status"]],
            -(item["value"] or 0.0) if item["status"] == "violated" else 0.0,
            ROLE_ORDER[item["role"]],
        )
    )
    return found


def ranking(
    folder: Path,
    method: Method = "sensitivity",
    response: str = "",
    limit: int = 50,
    active_only: bool = False,
    response_limit: int = 500,
) -> dict[str, Any]:
    """The design variables that matter most, and the responses.

    Args:
        folder: The run folder.
        method: How the variables are ranked.
        response: The column of the response they are ranked for; the objective
            (or the first response) by default. Unused by ``active``.
        limit: The number of variables returned at most.
        active_only: Return only the violated and active constraints, and the
            objective.
        response_limit: The number of responses returned at most.

    Returns:
        The best evaluation, the ranked variables (name, score, bound at the
        best evaluation), the responses (name, role, value, status) and the
        numbers of each.
    """
    table = load(folder)
    best = best_position(table)
    if best is None:
        msg = "The run has no evaluations."
        raise ResultsError(msg)
    inputs = table.by_role(*INPUT_ROLES)
    responses = _responses(table, best, active_only)
    if response:
        target = table.index_of(response)
    else:
        candidates = table.by_role("objective") or table.by_role(*RESPONSE_ROLES)
        target = candidates[0] if candidates else -1
    closeness, bounds = _at_bounds(table, inputs, best)
    note = ""
    if method == "active" or target < 0:
        scores = closeness
    elif method == "gradient":
        gradient, index = _gradient(folder, table, target, best)
        if len(gradient) != len(inputs):
            msg = "The gradients of the run do not match its design variables."
            raise ResultsError(msg)
        scores = np.abs(gradient) * _ranges(table, inputs)
        if index != best:
            note = f"Gradient of evaluation {index + 1}: the best one has none."
    else:
        scores = _correlations(table, inputs, target)
    order = np.argsort(-scores, kind="stable")[:limit]
    return {
        "method": method,
        "response": table.columns[target].name if target >= 0 else "",
        "evaluation": best + 1,
        "note": note,
        "inputs": [
            {
                "name": table.columns[inputs[i]].name,
                "score": float(scores[i]),
                "bound": bounds[i],
            }
            for i in order
        ],
        "responses": responses[:response_limit],
        "total_inputs": len(inputs),
        "total_responses": len(responses),
        "at_bounds": sum(bound is not None for bound in bounds),
    }
