"""Session-wide test setup.

No test may last more than one second (SPEC § 15.1), setup included. Importing
GEMSEO and PySide6 takes longer than that, so both are imported here, at
collection time, where the pytest-timeout limit does not apply. The single
QApplication of the session is created here for the same reason.
"""

import sys

# Imported for their cost, see the module docstring (sympy comes with analytic).
import gemseo.disciplines.analytic
import gemseo.disciplines.auto_py  # noqa: F401
from gemseo.algos.doe.factory import DOELibraryFactory
from gemseo.algos.opt.factory import OptimizationLibraryFactory
from gemseo.formulations.factory import MDOFormulationFactory
from gemseo.mda.factory import MDAFactory
from PySide6.QtWidgets import QApplication

QT_APPLICATION = QApplication.instance() or QApplication(sys.argv[:1])

# GEMSEO scans its classes the first time a factory is created.
MDAFactory().class_names  # noqa: B018
DOELibraryFactory().algorithms  # noqa: B018
OptimizationLibraryFactory().algorithms  # noqa: B018
MDOFormulationFactory().class_names  # noqa: B018


def pytest_addoption(parser):  # type: ignore[no-untyped-def]
    """``--update-golden`` rewrites the expected generated scripts."""
    parser.addoption(
        "--update-golden",
        action="store_true",
        help="Rewrite tests/python/codegen/golden/*.py; review the diff by hand.",
    )
