"""Reading the results of a run (runs in the worker; SPEC § 12).

The results are read from ``dataset.csv`` (written by the runner from the
GEMSEO database) and described with the variables of ``run.json``. Tables can
be large: rows are returned by pages, sorted and filtered here with NumPy,
and the last runs read are kept in memory. The values come from
``dataset.npy`` when the runner wrote it: parsing the text of a run with a
hundred thousand variables takes seconds.
"""

import csv
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from typing import Literal

import numpy as np
from pydantic import BaseModel

from gemseo_process_builder.results.models import RunInfo
from gemseo_process_builder.results.models import read_info

INEQUALITY_TOLERANCE = 1e-4
EQUALITY_TOLERANCE = 1e-2
"""GEMSEO's default tolerances, used for the ``feasible`` column."""

OPERATORS = {
    "<": np.less,
    "<=": np.less_equal,
    ">": np.greater,
    ">=": np.greater_equal,
    "==": np.equal,
    "!=": np.not_equal,
}


class ResultsError(Exception):
    """Results cannot be read; the message is for the user."""


class Filter(BaseModel):
    """Keep the rows whose column compares to a value (nothing is evaluated)."""

    column: str
    op: Literal["<", "<=", ">", ">=", "==", "!=", "between"]
    value: float | tuple[float, float]


class Sort(BaseModel):
    """Sort the rows by a column; unknown values come last."""

    column: str
    descending: bool = False


@dataclass
class Column:
    """A column of the results table: one component of a variable."""

    name: str
    """Like ``x_shared[1]``, or ``obj`` for a scalar."""

    variable: str
    component: int
    role: str

    def to_dict(self) -> dict[str, Any]:
        """The column as sent to the page."""
        return {
            "name": self.name,
            "variable": self.variable,
            "component": self.component,
            "role": self.role,
        }


@dataclass
class RunTable:
    """The results of a run as a table of numbers (NaN where unknown)."""

    info: RunInfo
    columns: list[Column]
    values: np.ndarray
    """One row per evaluation, one column per ``columns`` entry."""

    def __post_init__(self) -> None:
        self._positions = {column.name: i for i, column in enumerate(self.columns)}

    def index_of(self, name: str) -> int:
        """The position of a column."""
        try:
            return self._positions[name]
        except KeyError:
            msg = f"The results have no column {name}."
            raise ResultsError(msg) from None

    def by_role(self, *roles: str) -> list[int]:
        """The positions of the columns with these roles."""
        return [i for i, column in enumerate(self.columns) if column.role in roles]


def _read_dataset(path: Path) -> tuple[list[str], list[int], np.ndarray]:
    """Variable names, components and values of a GEMSEO ``dataset.csv``.

    Its first three lines give the group, the variable and the component of
    each column; the first column holds the row labels.
    """
    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.reader(file)
        next(reader)  # GROUP
        variables = next(reader)[1:]
        components = [int(value) for value in next(reader)[1:]]
        binary = path.with_suffix(".npy")
        if binary.exists():
            values = np.load(binary)
            if values.ndim == 2 and values.shape[1] == len(variables):
                return variables, components, values
        rows = [[_number(value) for value in row[1:]] for row in reader if row]
    values = np.array(rows, dtype=float).reshape(len(rows), len(variables))
    return variables, components, values


def _number(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return math.nan


def _feasibility(
    columns: list[Column], values: np.ndarray, info: RunInfo
) -> np.ndarray | None:
    """1 where every constraint holds, 0 elsewhere; ``None`` without constraints."""
    types = {
        v.name: v.constraint_type for v in info.variables if v.role == "constraint"
    }
    if not types:
        return None
    feasible = np.ones(len(values), dtype=bool)
    for position, column in enumerate(columns):
        kind = types.get(column.variable)
        if kind == "ineq":
            feasible &= values[:, position] <= INEQUALITY_TOLERANCE
        elif kind == "eq":
            feasible &= np.abs(values[:, position]) <= EQUALITY_TOLERANCE
    return feasible.astype(float)


def best_position(table: RunTable) -> int | None:
    """The row of the best evaluation, or ``None`` for an empty table.

    The smallest objective among the feasible evaluations (GEMSEO minimizes:
    a maximized objective is stored as its opposite); without a feasible one,
    the least violated evaluations; without an objective, the last one.
    """
    if not len(table.values):
        return None
    candidates = np.arange(len(table.values))
    feasible = table.by_role("feasibility")
    if feasible:
        kept = np.flatnonzero(table.values[:, feasible[0]] == 1)
        candidates = kept if len(kept) else _least_violated(table)
    objective = table.by_role("objective")
    if not objective:
        return int(candidates[-1])
    values = table.values[candidates, objective[0]]
    if np.isnan(values).all():
        return int(candidates[-1])
    return int(candidates[np.nanargmin(values)])


def _least_violated(table: RunTable) -> np.ndarray:
    """The rows whose largest constraint violation is the smallest."""
    types = {
        v.name: v.constraint_type
        for v in table.info.variables
        if v.role == "constraint"
    }
    violation = np.zeros(len(table.values))
    for position in table.by_role("constraint"):
        values = table.values[:, position]
        if types.get(table.columns[position].variable) == "eq":
            values = np.abs(values)
        violation = np.fmax(violation, values)
    return np.flatnonzero(violation == np.nanmin(violation))


@lru_cache(maxsize=3)
def _load(folder: str, stamp: tuple[float, float, float]) -> RunTable:
    """Read a run; ``stamp`` (modification times) invalidates the cache."""
    path = Path(folder)
    info = read_info(path)
    if info is None:
        msg = f"{path} is not a run folder."
        raise ResultsError(msg)
    dataset = path / "dataset.csv"
    if not dataset.exists():
        msg = f"The run {info.id} has no results."
        raise ResultsError(msg)
    variables, components, values = _read_dataset(dataset)
    roles = {variable.name: variable.role for variable in info.variables}
    sizes: dict[str, int] = {}
    for variable in variables:
        sizes[variable] = sizes.get(variable, 0) + 1
    columns = [
        Column(
            f"{variable}[{component}]" if sizes[variable] > 1 else variable,
            variable,
            component,
            roles.get(variable, "output"),
        )
        for variable, component in zip(variables, components, strict=True)
    ]
    # The evaluation number first, then the feasibility after the variables,
    # in one array stored column by column: the views read columns.
    columns.insert(0, Column("evaluation", "evaluation", 0, "index"))
    table = np.empty((len(values), len(columns) + 1), order="F")
    table[:, 0] = np.arange(1, len(values) + 1)
    table[:, 1:-1] = values
    del values
    feasible = _feasibility(columns, table[:, :-1], info)
    if feasible is None:
        return RunTable(info, columns, table[:, :-1])
    columns.append(Column("feasible", "feasible", 0, "feasibility"))
    table[:, -1] = feasible
    return RunTable(info, columns, table)


def load(folder: Path) -> RunTable:
    """The results of a run folder (cached for the last three runs)."""
    stamps = []
    for name in ("dataset.csv", "dataset.npy", "run.json"):
        file = folder / name
        stamps.append(file.stat().st_mtime if file.exists() else 0.0)
    return _load(str(folder.resolve()), (stamps[0], stamps[1], stamps[2]))


def _plain(values: np.ndarray) -> list[Any]:
    """Numbers for JSON: NaN becomes ``None``."""
    return [None if math.isnan(value) else float(value) for value in values]


def select(
    table: RunTable,
    sort: Sort | None = None,
    filters: list[Filter] | None = None,
    evaluations: list[int] | None = None,
) -> np.ndarray:
    """The positions of the rows kept by the filters, in the sorted order.

    Args:
        table: The results.
        sort: How to sort the rows.
        filters: Conditions on columns.
        evaluations: Keep only these evaluation numbers (a brushed selection).
    """
    keep = np.ones(len(table.values), dtype=bool)
    if evaluations is not None:
        keep &= np.isin(table.values[:, 0], evaluations)
    for item in filters or []:
        column = table.values[:, table.index_of(item.column)]
        if isinstance(item.value, tuple):
            low, high = item.value
            keep &= (column >= low) & (column <= high)
        elif item.op in OPERATORS:
            keep &= OPERATORS[item.op](column, item.value)
        else:
            msg = f"The filter {item.op} needs two values."
            raise ResultsError(msg)
    positions = np.flatnonzero(keep)
    if sort:
        column = table.values[positions, table.index_of(sort.column)]
        order = np.argsort(column, kind="stable")  # NaN last.
        if sort.descending:
            not_nan = order[~np.isnan(column[order])]
            nan = order[np.isnan(column[order])]
            order = np.concatenate([not_nan[::-1], nan])
        positions = positions[order]
    return positions


def rows(
    folder: Path,
    offset: int = 0,
    limit: int = 500,
    sort: Sort | None = None,
    filters: list[Filter] | None = None,
    evaluations: list[int] | None = None,
    names: list[str] | None = None,
) -> dict[str, Any]:
    """A page of rows, with the number of rows kept by the filters.

    Args:
        folder: The run folder.
        offset: The position of the first row of the page.
        limit: The number of rows of the page at most.
        sort: How to sort the rows.
        filters: Conditions on columns.
        evaluations: Keep only these evaluation numbers (a brushed selection).
        names: The columns to return; all of them by default.
    """
    table = load(folder)
    positions = select(table, sort, filters, evaluations)
    page = positions[offset : offset + limit]
    chosen = names or [column.name for column in table.columns]
    indices = [table.index_of(name) for name in chosen]
    return {
        "total": len(positions),
        "columns": chosen,
        "rows": [_plain(row) for row in table.values[np.ix_(page, np.array(indices))]],
    }


def matrix(folder: Path, names: list[str], max_rows: int = 5000) -> dict[str, Any]:
    """Columns of every row, or of evenly spaced rows beyond ``max_rows``.

    The charts drawing every point (scatter plots, parallel coordinates) use
    it; beyond ``max_rows`` they show bins or a sample (SPEC § 12.2).
    """
    table = load(folder)
    total = len(table.values)
    positions = np.arange(total)
    if total > max_rows:
        positions = np.unique(np.linspace(0, total - 1, max_rows).round().astype(int))
    indices = [table.index_of(name) for name in names]
    return {
        "total": total,
        "evaluations": _plain(table.values[positions, 0]),
        "columns": {
            name: _plain(table.values[positions, index])
            for name, index in zip(names, indices, strict=True)
        },
    }


def bin_range(values: np.ndarray) -> tuple[float, float]:
    """The range covered by the bins; a constant gets a width of 1."""
    finite = values[np.isfinite(values)]
    if not len(finite):
        return 0.0, 1.0
    low, high = float(finite.min()), float(finite.max())
    return (low - 0.5, high + 0.5) if low == high else (low, high)


def bin_indices(values: np.ndarray, low: float, high: float, bins: int) -> np.ndarray:
    """The bin of each value; the highest value goes in the last bin, NaN in -1.

    ``static/js/lib/binning.js`` does the same computation for small data.
    """
    finite = np.isfinite(values)
    scaled = np.floor((np.where(finite, values, low) - low) / (high - low) * bins)
    indices = np.clip(scaled, 0, bins - 1).astype(int)
    indices[~finite] = -1
    return indices


def binned(
    folder: Path,
    x: str,
    y: str,
    bins: int = 40,
    filters: list[Filter] | None = None,
) -> dict[str, Any]:
    """Counts of points in a grid of ``bins`` by ``bins`` rectangles."""
    table = load(folder)
    positions = select(table, None, filters)
    xs = table.values[positions, table.index_of(x)]
    ys = table.values[positions, table.index_of(y)]
    return bin_counts(xs, ys, bins)


def bin_counts(xs: np.ndarray, ys: np.ndarray, bins: int) -> dict[str, Any]:
    """Counts of points in ``counts[i][j]`` for x bin ``i`` and y bin ``j``."""
    x_range = bin_range(xs)
    y_range = bin_range(ys)
    ix = bin_indices(xs, *x_range, bins)
    iy = bin_indices(ys, *y_range, bins)
    counts = np.zeros((bins, bins), dtype=int)
    inside = (ix >= 0) & (iy >= 0)
    np.add.at(counts, (ix[inside], iy[inside]), 1)
    return {"x": list(x_range), "y": list(y_range), "counts": counts.tolist()}


def columns(folder: Path) -> list[dict[str, Any]]:
    """The columns of the results, with their roles."""
    return [column.to_dict() for column in load(folder).columns]


def summary(folder: Path) -> dict[str, Any]:
    """``run.json`` with the size of the results."""
    table = load(folder)
    return {
        **table.info.model_dump(mode="json"),
        "rows": len(table.values),
        "columns": len(table.columns),
    }


def history(folder: Path, names: list[str]) -> dict[str, Any]:
    """Some columns in evaluation order, for convergence charts."""
    table = load(folder)
    return {
        "evaluation": _plain(table.values[:, 0]),
        "values": {
            name: _plain(table.values[:, table.index_of(name)]) for name in names
        },
    }


def export_csv(
    folder: Path,
    path: Path,
    names: list[str] | None = None,
    sort: Sort | None = None,
    filters: list[Filter] | None = None,
    evaluations: list[int] | None = None,
) -> int:
    """Write a CSV with one header line; return the number of rows written."""
    table = load(folder)
    chosen = names or [column.name for column in table.columns]
    indices = [table.index_of(name) for name in chosen]
    positions = select(table, sort, filters, evaluations)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(chosen)
        for position in positions:
            writer.writerow(
                "" if math.isnan(value) else repr(float(value))
                for value in table.values[position, indices]
            )
    return len(positions)


GRADIENT_ROLES = ("objective", "constraint")
"""The functions whose gradients the Gradients view shows."""


def gradients(
    folder: Path,
    inputs: list[str] | None = None,
    functions: list[str] | None = None,
) -> dict[str, Any]:
    """The gradients of the objective and constraints at each iteration.

    They come from the database of the run (``history.h5``), where GEMSEO keeps
    the gradients the algorithm asked for; a run without derivatives has none.

    Args:
        folder: The run folder.
        inputs: The design variable columns of the last gradients; all by default.
        functions: The objective and constraints; all by default.

    Returns:
        The labels of the gradient components (the design variables, element by
        element), and per function: the iterations with a gradient, the norm of
        the gradient at each of them, and its last value.
    """
    from gemseo.algos.database import Database

    info = read_info(folder)
    if info is None:
        msg = f"{folder} is not a run folder."
        raise ResultsError(msg)
    labels = [
        f"{variable.name}[{index}]" if variable.size > 1 else variable.name
        for variable in info.variables
        if variable.role == "design variable"
        for index in range(variable.size)
    ]
    path = folder / "history.h5"
    functions = [
        variable.name
        for variable in info.variables
        if variable.role in GRADIENT_ROLES
        and (functions is None or variable.name in functions)
    ]
    # The last gradients of a run with many variables: only the chosen ones.
    positions = {label: index for index, label in enumerate(labels)}
    chosen = (
        [positions[name] for name in inputs if name in positions] if inputs else None
    )
    if chosen is not None:
        labels = [labels[index] for index in chosen]
    result: dict[str, Any] = {"labels": labels, "functions": []}
    if not path.exists():
        return result
    database = Database.from_hdf(path)
    roles = {variable.name: variable.role for variable in info.variables}
    for name in functions:
        key = database.get_gradient_name(name)
        iterations, norms, last = [], [], None
        for index, (_, values) in enumerate(database.items(), start=1):
            gradient = values.get(key)
            if gradient is None:
                continue
            array = np.atleast_2d(np.asarray(gradient, float))
            iterations.append(index)
            norms.append(float(np.linalg.norm(array)))
            last = array
        if last is not None and chosen is not None:
            last = last[:, chosen]
        if iterations:
            result["functions"].append(
                {
                    "name": name,
                    "role": roles[name],
                    "iterations": iterations,
                    "norms": norms,
                    # One row per component of the function (a vector constraint).
                    "last": [_plain(row) for row in last] if last is not None else [],
                }
            )
    return result
