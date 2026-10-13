"""Run every quality check of the project.

Usage:
    python tools/check.py          # run all checks
    python tools/check.py --fix    # apply ruff fixes and formatting first

Run it with the project's virtual environment interpreter.

Each check runs with the processes it starts in a group of its own (a Job
Object on Windows, a session on Linux and macOS), killed when the check ends: a
child left behind by a test (pytest stopped at the time limit ends at once)
cannot outlive the check and hold its output open.
"""

import argparse
import contextlib
import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

CHECKS = [
    ("ruff check", [PYTHON, "-m", "ruff", "check", "."]),
    ("ruff format", [PYTHON, "-m", "ruff", "format", "--check", "."]),
    ("mypy", [PYTHON, "-m", "mypy"]),
    # Too slow for a one-second test: generated scripts are type-checked here.
    ("mypy scripts", [PYTHON, "-m", "mypy", "tests/python/codegen/golden"]),
    # Apart: the examples have the same module names as the golden scripts.
    ("mypy examples", [PYTHON, "-m", "mypy", "examples"]),
    ("pytest", [PYTHON, "-m", "pytest"]),
    # The unit tests import only the pure modules: every module is parsed here.
    (
        "js syntax",
        [
            "node",
            "--experimental-vm-modules",
            "--no-warnings",
            "tools/check_js_syntax.mjs",
        ],
    ),
    # One process for all the files: the limit applies to each test, not to
    # the start of a Node.js process per file (slow on some CI machines).
    (
        "node tests",
        [
            "node",
            "--test",
            "--experimental-test-isolation=none",
            "--test-timeout=1000",
            "tests/js/**/*.test.js",
        ],
    ),
]

FIXES = [
    [PYTHON, "-m", "ruff", "check", "--fix", "."],
    [PYTHON, "-m", "ruff", "format", "."],
]


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class ProcessGroup:
    """A process and those it starts, killed together when the group closes."""

    def __init__(self) -> None:
        self.process: subprocess.Popen[bytes] | None = None
        self._job: Any = None

    def start(self, command: list[str]) -> subprocess.Popen[bytes]:
        """Start a command from the repository root in the group."""
        if sys.platform == "win32":
            self.process = subprocess.Popen(command, cwd=ROOT)
            self._job = _job_of(self.process)
        else:
            self.process = subprocess.Popen(command, cwd=ROOT, start_new_session=True)
        return self.process

    def close(self) -> None:
        """Kill what is left of the group."""
        if self.process is None:
            return
        if sys.platform == "win32":
            if self._job is not None:
                ctypes.WinDLL("kernel32").CloseHandle(self._job)  # Kills the job.
                self._job = None
            elif self.process.poll() is None:
                self.process.kill()
        else:
            # Nothing left once the session has ended.
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(self.process.pid, signal.SIGKILL)
        self.process = None


def _job_of(process: subprocess.Popen[bytes]) -> Any:
    """A Job Object killing its processes when closed, holding ``process``.

    The processes ``process`` starts belong to the job too. ``None`` when the
    job cannot be made (the process is then killed alone).
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    handle = int(process._handle)  # type: ignore[attr-defined]
    if not (
        kernel32.SetInformationJobObject(
            job,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        )
        and kernel32.AssignProcessToJobObject(job, handle)
    ):
        kernel32.CloseHandle(job)
        return None
    return job


def run(command: list[str]) -> bool:
    """Run a command from the repository root and tell whether it succeeded.

    What the command left running is killed when it ends.
    """
    group = ProcessGroup()
    try:
        return group.start(command).wait() == 0
    except FileNotFoundError as error:
        print(f"Cannot run {command[0]}: {error}")
        return False
    finally:
        group.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fix", action="store_true", help="apply ruff fixes first")
    arguments = parser.parse_args()

    if arguments.fix:
        for command in FIXES:
            run(command)

    results = []
    for name, command in CHECKS:
        print(f"\n=== {name} ===", flush=True)
        start = time.perf_counter()
        passed = run(command)
        results.append((name, passed, time.perf_counter() - start))

    print("\n=== Summary ===")
    for name, passed, duration in results:
        status = "PASS" if passed else "FAIL"
        print(f"{status}  {name:<13} {duration:6.1f} s")

    return 0 if all(passed for _, passed, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
