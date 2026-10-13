"""``tools/check.py`` kills what a check leaves running when it ends.

A child process left behind by a test (pytest stopped at the time limit ends
at once) would otherwise outlive the check and hold its output open: a CI job
hung for half an hour on 2026-10-13.
"""

import importlib.util
import sys
import time
from pathlib import Path

import psutil

TOOL = Path(__file__).parents[2] / "tools" / "check.py"

LEAVES_A_CHILD = """
import subprocess, sys
child = subprocess.Popen(
    [sys.executable, "-I", "-S", "-c", "import time; time.sleep(30)"]
)
open(sys.argv[1], "w").write(str(child.pid))
"""


def test_a_check_leaves_no_process_behind(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("gpb_check_tool", TOOL)
    assert spec is not None and spec.loader is not None
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    pid_file = tmp_path / "child.pid"
    command = [sys.executable, "-I", "-S", "-c", LEAVES_A_CHILD, str(pid_file)]
    assert check.run(command)
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 0.5
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == "zombie"
