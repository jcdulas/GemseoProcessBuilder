"""The data of projects, kept in the user data directory."""

import json
from pathlib import Path

from gemseo_process_builder.core.project_storage import ORIGIN
from gemseo_process_builder.core.project_storage import mark
from gemseo_process_builder.core.project_storage import move_into
from gemseo_process_builder.core.project_storage import prune
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
