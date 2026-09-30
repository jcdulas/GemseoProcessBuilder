"""A large-scale gradient-based optimizer for GEMSEO.

MMA and GCMMA with a working set of constraints.

Specified in docs/LARGE_SCALE_OPTIMIZER_SPEC.md of the GEMSEO Process Builder
repository.
"""

from gemseo_lso.core import DenseProblem
from gemseo_lso.core import LargeScaleProblem
from gemseo_lso.core import Optimizer
from gemseo_lso.core import ProblemError
from gemseo_lso.core import Report
from gemseo_lso.core import Result
from gemseo_lso.core import Settings
from gemseo_lso.core import SettingsError
from gemseo_lso.core import SparsityProbe
from gemseo_lso.core import State
from gemseo_lso.core import probe_sparsity

__version__ = "0.1.0"

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
