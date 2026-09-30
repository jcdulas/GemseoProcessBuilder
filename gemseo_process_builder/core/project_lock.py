"""Lock files of open projects (SPEC § 14.2).

An application opening a project writes its lock, with its process id and
host, in the folder of the data of the project (``core/project_storage.py``).
Another application of the same user opening the same project finds the lock
and opens the project read-only: two instances saving the same file would
overwrite each other's changes. A lock left by a process that no longer runs
(after a crash) is ignored.
"""

import contextlib
import json
import os
import socket
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psutil

from gemseo_process_builder.core.atomic_write import write_text_atomically


@dataclass(frozen=True)
class LockOwner:
    """The application holding a project."""

    pid: int
    host: str
    since: str

    def describe(self) -> str:
        """Who holds the project, for the user."""
        return (
            f"another instance (process {self.pid} on {self.host}, since {self.since})"
        )


def _read(path: Path) -> LockOwner | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return LockOwner(
            int(data["pid"]), str(data["host"]), str(data.get("since", ""))
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def owner_of(lock: Path) -> LockOwner | None:
    """The other application holding a lock file, if any.

    Locks of this process, and of processes of this host that stopped, are
    not owners.
    """
    owner = _read(lock)
    if owner is None:
        return None
    this_host = owner.host == socket.gethostname()
    if this_host and (owner.pid == os.getpid() or not psutil.pid_exists(owner.pid)):
        return None
    return owner


def acquire(lock: Path) -> LockOwner | None:
    """Take a lock file for this process.

    Returns:
        ``None`` when the project is now locked by this process, else the
        application holding it (the project must then be opened read-only).
    """
    owner = owner_of(lock)
    if owner is not None:
        return owner
    data = {
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "since": datetime.now().isoformat(timespec="seconds"),
    }
    # Where it cannot be written, the project is edited without a lock.
    with contextlib.suppress(OSError):
        lock.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomically(lock, json.dumps(data) + "\n")
    return None


def release(lock: Path) -> None:
    """Remove a lock file, if this process holds it."""
    owner = _read(lock)
    if (
        owner is not None
        and owner.pid == os.getpid()
        and owner.host == socket.gethostname()
    ):
        lock.unlink(missing_ok=True)
