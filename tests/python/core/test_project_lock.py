"""Lock files of open projects."""

import json
import os
import socket
from pathlib import Path

import psutil
import pytest
from golden_projects import example

from gemseo_process_builder.app.project_session import ProjectLockedError
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.core.project_lock import acquire
from gemseo_process_builder.core.project_lock import owner_of
from gemseo_process_builder.core.project_lock import release
from gemseo_process_builder.core.project_storage import LOCK


def other_instance(project: Path, pid: int | None = None) -> None:
    """A lock written by another running process of this host."""
    pid = pid or psutil.Process().ppid()
    data = {"pid": pid, "host": socket.gethostname(), "since": "2026-09-25T09:00:00"}
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text(json.dumps(data), encoding="utf-8")


def test_acquire_and_release(tmp_path: Path) -> None:
    project = tmp_path / "lock"
    assert acquire(project) is None
    assert json.loads(project.read_text())["pid"] == os.getpid()
    # This process holds it: it is no owner for itself.
    assert owner_of(project) is None
    release(project)
    assert not project.exists()


def test_other_instances_and_stale_locks(tmp_path: Path) -> None:
    project = tmp_path / "lock"
    other_instance(project)
    owner = acquire(project)
    assert owner is not None
    assert "another instance (process" in owner.describe()
    release(project)  # Not ours: kept.
    assert project.exists()
    # A process that stopped left its lock: it is ignored.
    other_instance(project, pid=4_000_000)
    assert acquire(project) is None


def test_a_locked_project_is_read_only(tmp_path: Path) -> None:
    project = tmp_path / "Sellar.py"
    session = ProjectSession(tmp_path / "data" / "untitled.gpb.json.autosave")
    session.project = example("sellar_mdf")
    session.save(project)
    session.release_lock()
    other_instance(session.storage_of(project) / LOCK)
    session.adopt(example("sellar_mdf"), script=project)  # Opened again.
    assert session.state()["read_only"].startswith("another instance")
    session.set_dirty()
    assert not session.write_autosave()
    with pytest.raises(ProjectLockedError, match="Save it under another name"):
        session.save()
    # Saved elsewhere, the project is editable again.
    copy = session.save(tmp_path / "Copy.py")
    assert session.locked_by is None
    lock = session.storage_of(copy) / LOCK
    assert owner_of(lock) is None
    assert lock.exists()
    assert not (tmp_path / "Copy.py.lock").exists()  # Not next to the script.
    session.new()
    assert not lock.exists()
