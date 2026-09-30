import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from gemseo_process_builder.app.preferences import MAX_RECENT_PROJECTS
from gemseo_process_builder.app.preferences import Preferences
from gemseo_process_builder.app.preferences import PreferencesStore


def test_defaults_when_the_file_does_not_exist(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path / "preferences.json")
    assert store.preferences == Preferences()
    assert store.preferences.max_undo == 500


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "preferences.json"
    PreferencesStore(path).update({"max_undo": 42, "catalog_paths": ["/a"]})
    reloaded = PreferencesStore(path).preferences
    assert reloaded.max_undo == 42
    assert reloaded.catalog_paths == ["/a"]


def test_corrupted_file_falls_back_to_defaults(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "preferences.json"
    path.write_text("{not json")
    store = PreferencesStore(path)
    assert store.preferences == Preferences()
    assert (tmp_path / "preferences.json.bak").read_text() == "{not json"
    assert "invalid" in caplog.text


def test_invalid_values_fall_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps({"max_undo": -3}))
    assert PreferencesStore(path).preferences.max_undo == 500


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps({"max_undo": 7, "from_the_future": True}))
    assert PreferencesStore(path).preferences.max_undo == 7


def test_invalid_update_changes_nothing(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path / "preferences.json")
    with pytest.raises(ValidationError):
        store.update({"max_undo": 0})
    assert store.preferences.max_undo == 500
    assert not store.path.exists()


def test_recent_projects(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path / "preferences.json")
    for index in range(MAX_RECENT_PROJECTS + 2):
        store.add_recent_project(f"p{index}")
    store.add_recent_project("p5")
    recent = store.preferences.recent_projects
    assert recent[0] == "p5"
    assert len(recent) == MAX_RECENT_PROJECTS
    assert recent.count("p5") == 1
