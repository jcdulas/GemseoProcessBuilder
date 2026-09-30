"""Writing files atomically (SPEC § 14.2).

The content goes to a temporary file next to the target, which then replaces
the target in one step: a crash or an error while writing leaves the previous
file intact, never a half-written one.
"""

import os
import tempfile
from pathlib import Path


def write_bytes_atomically(path: Path, data: bytes) -> None:
    """Write a file through a temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_text_atomically(path: Path, text: str) -> None:
    """Write a text file in UTF-8, through a temporary file (lines end with LF)."""
    write_bytes_atomically(path, text.encode("utf-8"))
