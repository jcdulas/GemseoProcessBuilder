"""Storing the surrogates of a project with their metadata."""

from pathlib import Path

import pytest

from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.core.serialization import load_project
from gemseo_process_builder.results.surrogates import SourceRun
from gemseo_process_builder.results.surrogates import SurrogateMetadata
from gemseo_process_builder.results.surrogates import SurrogateStore
from gemseo_process_builder.results.surrogates import SurrogateStoreError
from gemseo_process_builder.results.surrogates import SurrogateVariable
from gemseo_process_builder.results.surrogates import read_metadata


@pytest.fixture
def store(tmp_path: Path) -> SurrogateStore:
    session = ProjectSession(tmp_path / "untitled.gpb.json.autosave")
    session.save(tmp_path / "Plate.gpb.json")
    return SurrogateStore(session)


def metadata(name: str = "Plate RBF", run_id: str = "r-1") -> SurrogateMetadata:
    return SurrogateMetadata(
        id="s-1",
        name=name,
        algorithm="RBFRegressor",
        settings={"epsilon": 0.5},
        source=SourceRun(id=run_id, driver_name="Study"),
        inputs=[SurrogateVariable(name="x", lower=[-2], upper=[2], default=[0])],
        outputs=[SurrogateVariable(name="f")],
        n_samples=30,
        n_folds=5,
        quality={"f": {"r2": [1.0], "r2_cv": [0.93]}},
        created="2026-09-25T10:00:00+00:00",
        updated="2026-09-25T10:00:00+00:00",
    )


def trained(store: SurrogateStore) -> Path:
    """A model file as the worker writes it."""
    path = store.training_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"pickle")
    return path


def test_save_lists_and_round_trips(store: SurrogateStore) -> None:
    path = store.save(trained(store), metadata())
    assert path == store.folder() / "Plate_RBF.pkl"
    assert store.folder().name == "Plate.surrogates"
    (ref,) = store.session.project.surrogates
    assert (ref.id, ref.name, ref.model_path) == (
        "s-1",
        "Plate RBF",
        "Plate.surrogates/Plate_RBF.pkl",
    )
    assert read_metadata(path) == metadata()
    (entry,) = store.entries()
    assert not entry["missing"]
    assert entry["metadata"]["quality"]["f"]["r2_cv"] == [0.93]
    assert "RBFRegressor trained on 30 samples of the run r-1" in (metadata().summary())
    # The project keeps its surrogates.
    store.session.save(store.session.path)
    assert load_project(store.session.path).surrogates[0].name == "Plate RBF"


def test_names_are_unique_and_retraining_replaces(store: SurrogateStore) -> None:
    store.save(trained(store), metadata())
    with pytest.raises(SurrogateStoreError, match="already named"):
        store.save(trained(store), metadata())
    retrained = metadata("Plate GPR")
    retrained.id = "s-new"
    retrained.algorithm = "GaussianProcessRegressor"
    retrained.created = "2026-09-26T10:00:00+00:00"
    path = store.save(trained(store), retrained, replace="s-1")
    (ref,) = store.session.project.surrogates
    assert (ref.id, ref.name) == ("s-1", "Plate GPR")
    saved = read_metadata(path)
    assert saved is not None
    assert (saved.id, saved.algorithm) == ("s-1", "GaussianProcessRegressor")
    assert saved.created == "2026-09-25T10:00:00+00:00"
    assert not (store.folder() / "Plate_RBF.pkl").exists()
    assert not (store.folder() / "Plate_RBF.json").exists()


def test_a_deleted_run_is_flagged(store: SurrogateStore) -> None:
    path = store.save(trained(store), metadata())
    assert store.source_deleted("r-2") == 0
    assert store.source_deleted("r-1") == 1
    saved = read_metadata(path)
    assert saved is not None
    assert saved.source.deleted
    assert path.is_file()


def test_delete_and_missing_files(store: SurrogateStore) -> None:
    path = store.save(trained(store), metadata())
    path.unlink()
    assert store.entries()[0]["missing"]
    store.delete("s-1")
    assert store.session.project.surrogates == []
    assert not path.with_suffix(".json").exists()
    with pytest.raises(SurrogateStoreError, match="missing"):
        store.save(store.training_file(), metadata())
