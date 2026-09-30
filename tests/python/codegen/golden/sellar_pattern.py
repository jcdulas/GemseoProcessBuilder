"""The sparsity pattern imported by ``sellar_mdf_colored.py``.

Each constraint of Sellar depends on every design variable.
"""

import numpy as np
from scipy import sparse


def sellar_pattern(
    variables: list[tuple[str, int]], constraints: list[tuple[str, int]]
) -> sparse.csr_matrix:
    """Mark every variable as used by every constraint."""
    rows = sum(size for _, size in constraints)
    columns = sum(size for _, size in variables)
    return sparse.csr_matrix(np.ones((rows, columns), dtype=bool))
