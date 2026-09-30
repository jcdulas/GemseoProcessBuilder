"""The optimizer itself, on NumPy and SciPy only (spec § 3, § 5)."""

from gemseo_lso.core.optimizer import Optimizer
from gemseo_lso.core.optimizer import ProblemError
from gemseo_lso.core.problem import DenseProblem
from gemseo_lso.core.problem import LargeScaleProblem
from gemseo_lso.core.report import Report
from gemseo_lso.core.report import Result
from gemseo_lso.core.settings import Settings
from gemseo_lso.core.settings import SettingsError
from gemseo_lso.core.sparse_jacobian import SparsityProbe
from gemseo_lso.core.sparse_jacobian import probe_sparsity
from gemseo_lso.core.state import State

__all__ = [
    "DenseProblem",
    "LargeScaleProblem",
    "Optimizer",
    "ProblemError",
    "Report",
    "Result",
    "Settings",
    "SettingsError",
    "SparsityProbe",
    "State",
    "probe_sparsity",
]
