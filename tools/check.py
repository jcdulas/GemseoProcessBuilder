"""Run every quality check of the project.

Usage:
    python tools/check.py          # run all checks
    python tools/check.py --fix    # apply ruff fixes and formatting first

Run it with the project's virtual environment interpreter.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

CHECKS = [
    ("ruff check", [PYTHON, "-m", "ruff", "check", "."]),
    ("ruff format", [PYTHON, "-m", "ruff", "format", "--check", "."]),
    ("mypy", [PYTHON, "-m", "mypy"]),
    # Too slow for a one-second test: generated scripts are type-checked here.
    ("mypy scripts", [PYTHON, "-m", "mypy", "tests/python/codegen/golden"]),
    ("pytest", [PYTHON, "-m", "pytest"]),
    ("node tests", ["node", "--test", "--test-timeout=1000", "tests/js/**/*.test.js"]),
]

FIXES = [
    [PYTHON, "-m", "ruff", "check", "--fix", "."],
    [PYTHON, "-m", "ruff", "format", "."],
]


def run(command: list[str]) -> bool:
    """Run a command from the repository root and tell whether it succeeded."""
    try:
        return subprocess.run(command, cwd=ROOT, check=False).returncode == 0
    except FileNotFoundError as error:
        print(f"Cannot run {command[0]}: {error}")
        return False


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
        print(f"{status}  {name:<12} {duration:6.1f} s")

    return 0 if all(passed for _, passed, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
