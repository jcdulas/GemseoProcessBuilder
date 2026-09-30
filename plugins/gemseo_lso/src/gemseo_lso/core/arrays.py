"""The array types of the core, and stacking of rows."""

from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import sparse

Array = NDArray[np.float64]
"""Real values: points, gradients, rows."""

Indices = NDArray[np.intp]
"""Indices of constraints."""

Rows = Any
"""Rows of a Jacobian: a dense ``(k, n)`` array or a ``scipy.sparse`` matrix."""


def is_sparse(rows: Rows) -> bool:
    """Whether rows are a ``scipy.sparse`` matrix."""
    return bool(sparse.issparse(rows))


def stack_rows(blocks: list[Rows], size: int) -> Rows:
    """Stack blocks of rows; sparse if one of them is.

    Args:
        blocks: The blocks, each of shape ``(k, size)``.
        size: The number of variables.
    """
    blocks = [block for block in blocks if block.shape[0]]
    if not blocks:
        return np.zeros((0, size))
    if len(blocks) == 1:
        return blocks[0]
    if any(is_sparse(block) for block in blocks):
        return sparse.vstack(blocks, format="csr")
    return np.vstack(blocks)


def rows_times(rows: Rows, vector: Array) -> Array:
    """``rows @ vector``, in the precision of the rows, returned in float64.

    Multiplying float32 rows by a float64 vector would make NumPy copy the rows
    into float64 at each product: the vector is cast instead.
    """
    return np.asarray(rows @ vector.astype(rows.dtype, copy=False), dtype=float)


def times_rows(vector: Array, rows: Rows, dtype: type | None = float) -> Array:
    """``vector @ rows``, in the precision of the rows.

    Args:
        vector: The vector.
        rows: The rows.
        dtype: The type of the result; ``None`` keeps the one of the rows,
            without a conversion of the size of the design space.
    """
    cast = vector.astype(rows.dtype, copy=False)
    if is_sparse(rows):
        return np.asarray(rows.T @ cast, dtype=dtype).ravel()
    return np.asarray(cast @ rows, dtype=dtype)


def dense(rows: Rows) -> Array:
    """Rows as a dense array."""
    if is_sparse(rows):
        return np.asarray(rows.toarray(), dtype=float)
    return np.asarray(rows, dtype=float)
