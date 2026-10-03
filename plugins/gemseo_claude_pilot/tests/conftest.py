"""Setup of the tests of the copilot plugin.

No test may last more than one second (SPEC § 15.1), setup included. Importing
GEMSEO and running a first scenario take longer than that, so both happen here,
at collection time, where the pytest-timeout limit does not apply.
"""

import os

# No test reaches Claude: the pilot has no backend unless a test gives one.
os.environ["GEMSEO_CLAUDE_PILOT_BACKEND"] = "off"

import keyring
from gemseo.algos.doe.factory import DOELibraryFactory
from gemseo.algos.opt.factory import OptimizationLibraryFactory
from pilot_samples import rosenbrock
from pilot_samples import rosenbrock_doe
from pilot_samples import sellar
from pilot_samples import small_bilevel

from gemseo_claude_pilot.algorithms import gemseo_algorithms

# GEMSEO scans its classes the first time a factory is created.
OptimizationLibraryFactory().algorithms  # noqa: B018
DOELibraryFactory().algorithms  # noqa: B018
gemseo_algorithms("optimization")
gemseo_algorithms("doe")

# The scenarios the tests read, solved once.
sellar()
sellar(max_iter=2, maximize=True)

# The first runs of each algorithm the tests use import their libraries.
for algo_name in ("SLSQP", "NLOPT_COBYLA"):
    rosenbrock().execute(algo_name=algo_name, max_iter=3)
rosenbrock_doe().execute(algo_name="LHS", n_samples=3)
small_bilevel().execute(algo_name="NLOPT_COBYLA", max_iter=2)

# The keyring looks for the backends of the machine the first time.
keyring.get_keyring()

# The large-scale optimizer, when installed: Numba compiles its kernels the first
# time they run (or loads them from its cache), and h5py is slow to import.
try:
    import h5py  # noqa: F401

    from gemseo_lso.core.kernels import warm_up
except ImportError:
    pass
else:
    warm_up()
