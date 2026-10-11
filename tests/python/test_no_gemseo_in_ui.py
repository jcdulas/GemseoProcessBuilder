"""The UI process never imports GEMSEO (SPEC § 14.2): only the worker and the
runner do.

``conftest.py`` imports GEMSEO for the other tests, so the check runs in a
fresh interpreter. It imports every module of ``app`` and ``core``, except the
two that assemble the window (they import Qt WebEngine's widgets, too slow to
load in a one-second test, and nothing that the other modules do not).
"""

import subprocess
import sys

CHECK = """
import importlib, pkgutil, sys
import gemseo_process_builder.app as app
import gemseo_process_builder.core as core
skipped = {"app.application", "app.main_window"}
for package in (app, core):
    for module in pkgutil.iter_modules(package.__path__):
        name = f"{package.__name__.split('.')[-1]}.{module.name}"
        if name not in skipped:
            importlib.import_module(f"gemseo_process_builder.{name}")
loaded = [name for name in sys.modules if name.split(".")[0] == "gemseo"]
print(sorted(loaded))
"""


# Started at collection, where the one-second limit does not apply: the fresh
# interpreter takes half a second to load Qt and the modules (0.7 s on CI).
PROCESS = subprocess.Popen(
    [sys.executable, "-c", CHECK],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)


def test_the_ui_modules_do_not_import_gemseo() -> None:
    stdout, stderr = PROCESS.communicate(timeout=5)
    assert PROCESS.returncode == 0, stderr
    assert stdout.strip() == "[]"
