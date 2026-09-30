"""The row cache: the gradients of the constraints, by index (spec § 3.5).

Every row is kept with the iteration it was computed at. With the policy
``always``, the rows of an iteration are computed at its iterate (the cache
then only serves the repairs of the screening within the iteration). With
``near_active``, a row of a constraint far from activity may be reused while
it is young and the iterate has moved little since.

The rows are kept in the blocks the problem gave, with, for each constraint,
its block and its position in it: splitting a block into single rows costs a
Python call per row (4.7 s for 90,000 sparse rows), gathering them back one
fancy index per block.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from gemseo_lso.core.arrays import Array
from gemseo_lso.core.arrays import Indices
from gemseo_lso.core.arrays import Rows
from gemseo_lso.core.arrays import stack_rows
from gemseo_lso.core.settings import Settings

Fetch = Callable[[Indices], Rows]
"""Ask the problem for the rows of some constraints at the current iterate."""


@dataclass
class _Block:
    """Rows given at once by the problem."""

    rows: Rows
    iteration: int
    """The iteration they were computed at."""

    users: int
    """The constraints still referring to a row of the block."""


class RowCache:
    """The rows of the constraints of the working set."""

    def __init__(self, size: int) -> None:
        """
        Args:
            size: The number of variables.
        """  # noqa: D205, D212
        self.size = size
        self._blocks: dict[int, _Block] = {}
        self._where: dict[int, tuple[int, int]] = {}
        """For each constraint, its block and its position in the block."""

        self._next_block = 0
        self._points: dict[int, Array] = {}
        self._moved: dict[int, float] = {}
        """How far the iterate moved since each iteration of computation."""

    def __len__(self) -> int:
        return len(self._where)

    def rows(
        self,
        indices: Indices,
        x: Array,
        iteration: int,
        fresh: NDArray[np.bool_],
        ranges: Array,
        settings: Settings,
        fetch: Fetch,
    ) -> tuple[Rows, int, int]:
        """The rows of some constraints at ``x``, computed or reused.

        Args:
            indices: The constraints, sorted.
            x: The iterate.
            iteration: Its index.
            fresh: For each constraint, whether its row must be computed at
                ``x`` (close to activity).
            ranges: The ranges of the variables.
            settings: The settings.
            fetch: Computes rows at ``x``.

        Returns:
            The rows in the order of ``indices``, and the numbers of rows
            computed and reused.
        """
        self._points[iteration] = x
        self._moved = {}
        needed = []
        reused = 0
        for position, index in enumerate(indices.tolist()):
            where = self._where.get(index)
            if where is not None:
                computed_at = self._blocks[where[0]].iteration
                if computed_at == iteration:
                    continue
                if self._reusable(
                    computed_at, x, iteration, bool(fresh[position]), ranges, settings
                ):
                    reused += 1
                    continue
            needed.append(index)
        batch = settings.row_batch_size or max(len(needed), 1)
        whole = None
        for start in range(0, len(needed), batch):
            chunk = np.asarray(needed[start : start + batch], dtype=np.intp)
            block = fetch(chunk)
            if len(needed) == len(indices) and batch >= len(needed):
                whole = block  # The rows asked for, in order: no copy.
            self._store(chunk, block, iteration)
        if whole is not None:
            return whole, len(needed), reused
        return self._gather(indices), len(needed), reused

    def _store(self, indices: Indices, block: Rows, iteration: int) -> None:
        """Keep a block of rows and where each of its constraints is."""
        number = self._next_block
        self._next_block += 1
        self._blocks[number] = _Block(block, iteration, len(indices))
        for position, index in enumerate(indices.tolist()):
            self._forget(index)
            self._where[index] = (number, position)

    def _forget(self, index: int) -> None:
        """Drop the row of a constraint, and its block once no row is used."""
        where = self._where.pop(index, None)
        if where is None:
            return
        block = self._blocks[where[0]]
        block.users -= 1
        if not block.users:
            del self._blocks[where[0]]

    def _gather(self, indices: Indices) -> Rows:
        """The rows of some constraints, in their order: one index per block."""
        by_block: dict[int, list[tuple[int, int]]] = {}
        for order, index in enumerate(indices.tolist()):
            number, position = self._where[index]
            by_block.setdefault(number, []).append((order, position))
        parts = []
        orders: list[int] = []
        for number, entries in by_block.items():
            orders.extend(entry[0] for entry in entries)
            positions = np.asarray([entry[1] for entry in entries])
            parts.append(self._blocks[number].rows[positions])
        stacked = stack_rows(parts, self.size)
        if orders == sorted(orders):
            return stacked
        permutation = np.argsort(np.asarray(orders), kind="stable")
        return stacked[permutation]

    def _reusable(
        self,
        computed_at: int,
        x: Array,
        iteration: int,
        fresh: bool,
        ranges: Array,
        settings: Settings,
    ) -> bool:
        if settings.row_refresh != "near_active" or fresh:
            return False
        if iteration - computed_at > settings.max_row_age:
            return False
        if computed_at not in self._moved:
            # Once per iteration of computation, not once per row.
            point = self._points.get(computed_at)
            self._moved[computed_at] = (
                np.inf
                if point is None
                else float(np.max(np.abs(x - point) / ranges, initial=0.0))
            )
        return self._moved[computed_at] <= settings.max_row_step

    def keep(self, indices: Indices) -> None:
        """Forget the rows of the constraints out of ``indices``.

        And the iterates no row was computed at, but the latest.
        """
        wanted = set(indices.tolist())
        for index in [index for index in self._where if index not in wanted]:
            self._forget(index)
        used = {block.iteration for block in self._blocks.values()}
        latest = max(self._points, default=None)
        for iteration in list(self._points):
            if iteration not in used and iteration != latest:
                del self._points[iteration]
