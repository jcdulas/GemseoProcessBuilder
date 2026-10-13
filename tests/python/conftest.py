"""Session-wide test setup.

No test may last more than one second (SPEC § 15.1), setup included. Importing
GEMSEO and PySide6 takes longer than that, so both are imported here, at
collection time, where the pytest-timeout limit does not apply. The single
QApplication of the session is created here for the same reason.
"""

import os
import sys
from collections.abc import Iterator
from typing import Any

# Imported for their cost, see the module docstring (sympy comes with analytic).
import gemseo.disciplines.analytic
import gemseo.disciplines.auto_py  # noqa: F401
import keyring
import matplotlib.pyplot
import pytest
from gemseo.algos.doe.factory import DOELibraryFactory
from gemseo.algos.opt.factory import OptimizationLibraryFactory
from gemseo.formulations.factory import MDOFormulationFactory
from gemseo.mda.factory import MDAFactory
from gemseo.mlearning.regression.algos.factory import RegressorFactory
from gemseo.post.factory import PostFactory
from gemseo.post.opt_history_view import OptHistoryView  # noqa: F401
from PySide6.QtWidgets import QApplication

from gemseo_process_builder.core.units import check as units_check

# No test reaches Claude: a piloted script read or run has no backend.
os.environ["GEMSEO_CLAUDE_PILOT_BACKEND"] = "off"

# The workers save figures without opening windows.
matplotlib.use("Agg")

QT_APPLICATION = QApplication.instance() or QApplication(sys.argv[:1])

# GEMSEO scans its classes the first time a factory is created.
MDAFactory().class_names  # noqa: B018
DOELibraryFactory().algorithms  # noqa: B018
OptimizationLibraryFactory().algorithms  # noqa: B018
MDOFormulationFactory().class_names  # noqa: B018
PostFactory().class_names  # noqa: B018
RegressorFactory().class_names  # noqa: B018 (imports scikit-learn)

# The keyring of the machine is looked for the first time it is used (the
# copilot's API key, with the plugin installed).
keyring.get_keyring()

# pint's registry is slow to create: once, here.
units_check("mm", "m")


def pytest_addoption(parser):  # type: ignore[no-untyped-def]
    """``--update-golden`` rewrites the expected generated scripts."""
    parser.addoption(
        "--update-golden",
        action="store_true",
        help="Rewrite tests/python/codegen/golden/*.py; review the diff by hand.",
    )


GEMSEO_MANAGER = "gemseo.utils.multiprocessing.manager"
"""GEMSEO's module holding its process-wide multiprocessing manager."""


class InProcessManager:
    """Stands for GEMSEO's multiprocessing manager in one process: no child.

    GEMSEO's full caches (HDF5, memory) share their index through the manager
    of ``get_multi_processing_manager()``, a server process started on first use
    and alive until the interpreter exits.
    """

    def dict(self) -> dict[Any, Any]:
        """A dictionary of this process."""
        return {}

    def list(self, items: Any = ()) -> list[Any]:
        """A list of this process."""
        return list(items)

    def shutdown(self) -> None:
        """Nothing to stop."""


@pytest.fixture
def in_process_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """GEMSEO's caches without the server process of its manager (and its spawn)."""
    module = sys.modules[GEMSEO_MANAGER]
    monkeypatch.setitem(vars(module), "__manager", InProcessManager())


@pytest.fixture(autouse=True)
def no_multiprocessing_manager_left() -> Iterator[None]:
    """Stop GEMSEO's multiprocessing manager after the test that started it.

    Its server process inherits the output of pytest: when pytest is stopped at
    the time limit (``os._exit``), it outlives it and holds the pipe of the CI
    step open (2026-10-13: a job hung for half an hour).
    """
    yield
    module = sys.modules.get(GEMSEO_MANAGER)
    manager = vars(module).get("__manager") if module is not None else None
    if manager is not None:
        manager.shutdown()
        vars(module)["__manager"] = None
