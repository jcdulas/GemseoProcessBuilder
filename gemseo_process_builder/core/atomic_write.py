"""Writing files atomically (SPEC § 14.2).

The content goes to a temporary file next to the target, which then replaces
the target in one step: a crash or an error while writing leaves the previous
file intact, never a half-written one.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

RETRY_PAUSES: tuple[float, ...] = (
    (0.01, 0.02, 0.04, 0.08, 0.16, 0.32) if sys.platform == "win32" else ()
)
"""The pauses, in seconds, before a replacement Windows refused is tried again.

An antivirus or the search indexer opening a file that was just written makes
Windows refuse to replace it for a moment (access denied, WinError 5): a Python
file created then saved at once failed so on a CI machine. Elsewhere an access
denied is not transient."""


def _replace(source: str, target: Path) -> None:
    """``os.replace``, tried again after each of ``RETRY_PAUSES`` if refused."""
    for pause in (*RETRY_PAUSES, None):
        try:
            os.replace(source, target)
        except PermissionError:
            if pause is None:
                raise
            time.sleep(pause)
        else:
            return


def write_bytes_atomically(path: Path, data: bytes) -> None:
    """Write a file through a temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
        _replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_text_atomically(path: Path, text: str) -> None:
    """Write a text file in UTF-8, through a temporary file (lines end with LF)."""
    write_bytes_atomically(path, text.encode("utf-8"))
