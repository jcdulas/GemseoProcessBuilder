"""Reading the results of a run (runs in the worker; SPEC § 12).

The results are read from ``dataset.csv`` (written by the runner from the
GEMSEO database) and described with the variables of ``run.json``. Tables can
be large: rows are returned by pages, sorted and filtered here with NumPy,
and the last runs read are kept in memory.
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

    def index_of(self, name: str) -> int:
        """The position of a column."""
        for index, column in enumerate(self.columns):
            if column.name == name:
                return index
        msg = f"The results have no column {name}."
        raise ResultsError(msg)


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


@lru_cache(maxsize=3)
def _load(folder: str, stamp: tuple[float, float]) -> RunTable:
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
    # The evaluation number first, then the feasibility after the variables.
    number = np.arange(1, len(values) + 1, dtype=float)[:, None]
    columns.insert(0, Column("evaluation", "evaluation", 0, "index"))
    values = np.hstack([number, values])
    feasible = _feasibility(columns, values, info)
    if feasible is not None:
        columns.append(Column("feasible", "feasible", 0, "feasibility"))
        values = np.hstack([values, feasible[:, None]])
    return RunTable(info, columns, values)


def load(folder: Path) -> RunTable:
    """The results of a run folder (cached for the last three runs)."""
    stamps = []
    for name in ("dataset.csv", "run.json"):
        file = folder / name
        stamps.append(file.stat().st_mtime if file.exists() else 0.0)
    return _load(str(folder.resolve()), (stamps[0], stamps[1]))


def _plain(values: np.ndarray) -> list[Any]:
    """Numbers for JSON: NaN becomes ``None``."""
    return [None if math.isnan(value) else float(value) for value in values]


def select(
    table: RunTable, sort: Sort | None = None, filters: list[Filter] | None = None
) -> np.ndarray:
    """The positions of the rows kept by the filters, in the sorted order."""
    keep = np.ones(len(table.values), dtype=bool)
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
) -> dict[str, Any]:
    """A page of rows, with the number of rows kept by the filters."""
    table = load(folder)
    positions = select(table, sort, filters)
    page = positions[offset : offset + limit]
    return {
        "total": len(positions),
        "columns": [column.name for column in table.columns],
        "rows": [_plain(table.values[position]) for position in page],
    }


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
) -> int:
    """Write a CSV with one header line; return the number of rows written."""
    table = load(folder)
    chosen = names or [column.name for column in table.columns]
    indices = [table.index_of(name) for name in chosen]
    positions = select(table, sort, filters)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(chosen)
        for position in positions:
            writer.writerow(
                "" if math.isnan(value) else repr(float(value))
                for value in table.values[position, indices]
            )
    return len(positions)
