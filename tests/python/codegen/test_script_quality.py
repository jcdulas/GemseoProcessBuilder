"""The golden and example scripts pass ruff with its default settings.

The rules are those a careful developer enables; mypy runs on the same files
in ``tools/check.py``, being too slow for a one-second test.
"""

import subprocess
import sys
from pathlib import Path

GOLDEN = Path(__file__).parent / "golden"
EXAMPLES = Path(__file__).parents[3] / "examples"
RUFF = [sys.executable, "-m", "ruff"]
SETTINGS = ["--isolated", "--no-cache", "--line-length", "88"]
RULES = ["--select", "E,F,W,I,N,UP,B,SIM,RUF,D", "--ignore", "D203,D213"]


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*RUFF, *arguments, str(GOLDEN), str(EXAMPLES)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_generated_scripts_pass_ruff_check() -> None:
    result = run("check", *SETTINGS, "--target-version", "py312", *RULES)
    assert result.returncode == 0, result.stdout


def test_generated_scripts_are_formatted() -> None:
    result = run("format", "--check", *SETTINGS)
    assert result.returncode == 0, result.stdout
