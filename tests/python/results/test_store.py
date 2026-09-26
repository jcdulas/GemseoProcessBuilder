import shutil
from pathlib import Path

import pytest

from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.results.models import RunInfo
from gemseo_process_builder.results.models import read_info
from gemseo_process_builder.results.rediscovery import rediscover
from gemseo_process_builder.results.store import RunStore
from gemseo_process_builder.results.store import RunStoreError

SELLAR_RUN = Path(__file__).parent / "fixtures" / "sellar_run"


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    session = ProjectSession(tmp_path / "untitled.gpb.json.autosave")
    session.save(tmp_path / "Sellar.py")
    return RunStore(session)


def add_run(store: RunStore, run_id: str = "r-1") -> Path:
    folder = store.folder() / run_id
    shutil.copytree(SELLAR_RUN, folder)
    info = read_info(folder)
    assert info is not None
    info.id = run_id
    store.add(info, folder)
    return folder


def test_index_and_entries(store: RunStore) -> None:
    assert store.folder() == store.session.storage / "runs"
    folder = add_run(store)
    assert store.session.state()["dirty"]
    (ref,) = store.session.project.runs
    assert ref.run_path == str(store.folder() / "r-1")
    (entry,) = store.entries()
    assert (entry["missing"], entry["status"], entry["driver_name"]) == (
        False,
        "completed",
        "Optimizer",
    )
    assert Path(entry["folder"]) == folder


def test_rename(store: RunStore) -> None:
    folder = add_run(store)
    store.rename("r-1", " Baseline ")
    info = read_info(folder)
    assert info is not None and info.name == "Baseline"
    with pytest.raises(RunStoreError, match="not in the project"):
        store.rename("r-2", "x")


def test_delete(store: RunStore) -> None:
    folder = add_run(store)
    store.delete("r-1")
    assert not folder.exists()
    assert store.session.project.runs == []


def test_orphans_in_both_directions(store: RunStore) -> None:
    add_run(store, "r-1")
    orphan = store.folder() / "r-2"
    shutil.copytree(SELLAR_RUN, orphan)
    (store.folder() / "not-a-run").mkdir()
    assert [found["id"] for found in store.orphans()] == ["r-20260924-101500"]
    assert store.import_orphans(["r-20260924-101500"]) == 1
    assert [ref.id for ref in store.session.project.runs] == [
        "r-1",
        "r-20260924-101500",
    ]
    assert store.orphans() == []
    shutil.rmtree(store.folder() / "r-1")
    missing = [entry["id"] for entry in store.entries() if entry["missing"]]
    assert missing == ["r-1"]
    assert store.forget_missing() == 1
    assert [ref.id for ref in store.session.project.runs] == ["r-20260924-101500"]


def test_runs_are_found_again_next_to_the_script(
    store: RunStore, tmp_path: Path
) -> None:
    add_run(store)
    read = Project()  # As read from the script: without its runs.
    read.metadata.name = "Sellar"
    rediscover(read, store.session.storage)
    reopened = ProjectSession(tmp_path / "other.autosave")
    reopened.adopt(read, script=tmp_path / "Sellar.py")
    (entry,) = RunStore(reopened).entries()
    assert entry["summary"]["objective"] == "obj"


def test_run_info_accepts_unknown_keys() -> None:
    info = RunInfo.model_validate(
        {"id": "r", "driver": "d", "driver_name": "D", "created": "now", "future": 1}
    )
    assert info.schema_version == 1
