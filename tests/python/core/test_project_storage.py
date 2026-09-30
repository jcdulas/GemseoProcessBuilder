"""The data of projects, kept in the user data directory."""

import json
from pathlib import Path

from golden_projects import example

from gemseo_process_builder.core.project_storage import ORIGIN
from gemseo_process_builder.core.project_storage import find_moved
from gemseo_process_builder.core.project_storage import mark
from gemseo_process_builder.core.project_storage import move_into
from gemseo_process_builder.core.project_storage import prune
from gemseo_process_builder.core.project_storage import record
from gemseo_process_builder.core.project_storage import storage_folder


def test_each_project_file_has_its_own_folder(tmp_path: Path) -> None:
    root = tmp_path / "data"
    sellar = storage_folder(root, tmp_path / "work" / "sellar.py")
    assert sellar.parent == root / "projects"
    assert sellar.name.startswith("sellar-")
    assert sellar == storage_folder(
        root, tmp_path / "work" / ".." / "work" / "sellar.py"
    )
    assert sellar != storage_folder(root, tmp_path / "other" / "sellar.py")
    assert storage_folder(root, None) == root / "projects" / "untitled"
    mark(sellar, tmp_path / "work" / "sellar.py")
    origin = json.loads((sellar / ORIGIN).read_text("utf-8"))
    assert origin["path"] == str((tmp_path / "work" / "sellar.py").resolve())


def test_moving_folders_keeps_what_is_taken(tmp_path: Path) -> None:
    source, target = tmp_path / "Sellar.runs", tmp_path / "runs"
    for name in ("r-1", "r-2"):
        (source / name).mkdir(parents=True)
    (target / "r-2").mkdir(parents=True)
    moved = move_into(source, target)
    assert moved == {source / "r-1": target / "r-1"}
    assert (source / "r-2").is_dir()  # Its name is taken: left in place.
    assert move_into(tmp_path / "missing", target) == {}


def test_a_folder_left_empty_is_removed(tmp_path: Path) -> None:
    storage = tmp_path / "sellar-1234"
    mark(storage, tmp_path / "sellar.py")
    (storage / "runs").mkdir()
    prune(storage)
    assert not storage.exists()
    mark(storage, tmp_path / "sellar.py")
    (storage / "runs" / "r-1").mkdir(parents=True)
    prune(storage)
    assert storage.exists()


def test_a_moved_script_finds_its_folder_again(tmp_path: Path) -> None:
    root = tmp_path / "data"
    study = example("sellar_mdf")
    old = tmp_path / "old" / "sellar.py"
    old.parent.mkdir()
    old.write_text("print('sellar')\n", "utf-8")
    storage = storage_folder(root, old)
    mark(storage, old)
    record(storage, old, study)
    moved = tmp_path / "new" / "sellar.py"
    moved.parent.mkdir()
    # Copied: the original is still there, its folder stays with it.
    moved.write_text("print('sellar')\n", "utf-8")
    assert find_moved(root, moved, study) == (None, [])
    # Moved, but nothing to find again: no runs nor surrogates.
    old.unlink()
    assert find_moved(root, moved, study) == (None, [])
    (storage / "runs" / "r-1").mkdir(parents=True)
    assert find_moved(root, moved, study) == (storage, [])
    # Then edited: the same tree of the model.
    moved.write_text("print('sellar, edited')\n", "utf-8")
    assert find_moved(root, moved, study) == (storage, [])
    changed = example("sellar_mdf")
    changed.root.children[0].name = "Other"
    assert find_moved(root, moved, changed) == (None, [])
    # Two moved projects with the same fingerprint: which one is unknown.
    other = tmp_path / "other.py"
    mark(storage_folder(root, other), other)
    other.write_text("print('sellar')\n", "utf-8")
    record(storage_folder(root, other), other, study)
    (storage_folder(root, other) / "surrogates").mkdir()
    (storage_folder(root, other) / "surrogates" / "model.pkl").write_bytes(b"")
    other.unlink()
    moved.write_text("print('sellar')\n", "utf-8")
    found, ambiguous = find_moved(root, moved, study)
    assert found is None
    assert len(ambiguous) == 2
