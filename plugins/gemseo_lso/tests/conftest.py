"""Setup of the tests of the large-scale optimizer.

No test may last more than one second (SPEC § 15.1), setup included: the
libraries slow to import for the first time are imported here, at collection
time, where the pytest-timeout limit does not apply.
"""

import h5py  # noqa: F401
import nlopt  # noqa: F401
import scipy.optimize  # noqa: F401

from gemseo_lso.core.kernels import warm_up

# Numba compiles its kernels the first time they run (or loads them from its
# cache): seconds, out of the tests.
warm_up()


def _run_gemseo_once() -> None:
    """A small MDF scenario on LSO_GCMMA, and an analytic discipline.

    GEMSEO loads its factories, its MDAs and its formulations lazily: 0.7 s the
    first time.
    """
    import logging

    from gemseo import create_scenario
    from gemseo.problems.mdo.sellar.sellar_1 import Sellar1
    from gemseo.problems.mdo.sellar.sellar_2 import Sellar2
    from gemseo.problems.mdo.sellar.sellar_design_space import SellarDesignSpace
    from gemseo.problems.mdo.sellar.sellar_system import SellarSystem

    logging.getLogger("gemseo").setLevel(logging.WARNING)
    logging.getLogger("gemseo_lso").setLevel(logging.WARNING)
    scenario = create_scenario(
        [Sellar1(), Sellar2(), SellarSystem()],
        "obj",
        SellarDesignSpace(),
        formulation_name="MDF",
    )
    scenario.add_constraint("c_1", "ineq")
    scenario.execute(algo_name="LSO_GCMMA", max_iter=3)
    # The first analytic discipline parses its formulas with SymPy: 0.6 s.
    from gemseo import create_discipline

    create_discipline("AnalyticDiscipline", expressions={"y": "x**2"}).execute()


_run_gemseo_once()
