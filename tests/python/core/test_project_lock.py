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
from gemseo_process_builder.core.project_lock import lock_path
from gemseo_process_builder.core.project_lock import owner_of
from gemseo_process_builder.core.project_lock import release


def other_instance(project: Path, pid: int | None = None) -> None:
    """A lock written by another running process of this host."""
    pid = pid or psutil.Process().ppid()
    data = {"pid": pid, "host": socket.gethostname(), "since": "2026-09-25T09:00:00"}
    lock_path(project).write_text(json.dumps(data), encoding="utf-8")


def test_acquire_and_release(tmp_path: Path) -> None:
    project = tmp_path / "Sellar.py"
    assert acquire(project) is None
    assert json.loads(lock_path(project).read_text())["pid"] == os.getpid()
    # This process holds it: it is no owner for itself.
    assert owner_of(project) is None
    release(project)
    assert not lock_path(project).exists()


def test_other_instances_and_stale_locks(tmp_path: Path) -> None:
    project = tmp_path / "Sellar.py"
    other_instance(project)
    owner = acquire(project)
    assert owner is not None
    assert "another instance (process" in owner.describe()
    release(project)  # Not ours: kept.
    assert lock_path(project).exists()
    # A process that stopped left its lock: it is ignored.
    other_instance(project, pid=4_000_000)
    assert acquire(project) is None


def test_a_locked_project_is_read_only(tmp_path: Path) -> None:
    project = tmp_path / "Sellar.py"
    session = ProjectSession(tmp_path / "untitled.gpb.json.autosave")
    session.project = example("sellar_mdf")
    session.save(project)
    session.release_lock()
    other_instance(project)
    session.adopt(example("sellar_mdf"), script=project)  # Opened again.
    assert session.state()["read_only"].startswith("another instance")
    session.set_dirty()
    assert not session.write_autosave()
    with pytest.raises(ProjectLockedError, match="Save it under another name"):
        session.save()
    # Saved elsewhere, the project is editable again.
    copy = session.save(tmp_path / "Copy.py")
    assert session.locked_by is None
    assert owner_of(copy) is None
    assert lock_path(copy).exists()
    session.new()
    assert not lock_path(copy).exists()
