"""Session-wide test setup.

No test may last more than one second (SPEC § 15.1), setup included. Importing
GEMSEO and PySide6 takes longer than that, so both are imported here, at
collection time, where the pytest-timeout limit does not apply. The single
QApplication of the session is created here for the same reason.
"""

import sys

import gemseo  # noqa: F401  (imported for its cost, see the module docstring)
from PySide6.QtWidgets import QApplication

QT_APPLICATION = QApplication.instance() or QApplication(sys.argv[:1])
