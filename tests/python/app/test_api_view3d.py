"""nastran_view started for one evaluation, or two compared (plan 80)."""

from pathlib import Path
from typing import Any

import pytest

from gemseo_process_builder.app import api_view3d
from gemseo_process_builder.app.api_view3d import OpenParams
from gemseo_process_builder.app.api_view3d import View3dService
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.preferences import PreferencesStore


class Store:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def entries(self) -> list[dict[str, Any]]:
        return [{"id": "r-1", "folder": str(self.folder)}]


class Worker:
    def __init__(self, available: bool = True) -> None:
        self.available = available

    def call(self, method: str, params: dict[str, Any], timeout: float) -> Any:
        assert method == "view3d.state"
        return {
            "available": self.available,
            "reason": "" if self.available else "nastran_view is not installed.",
            "store": "D:/store",
            "folders": {"1": "D:/store/a", "2": "D:/store/b"},
            "problems": [],
        }


def service(tmp_path: Path, available: bool = True) -> View3dService:
    preferences = PreferencesStore(tmp_path / "prefs.json")
    preferences.preferences.python_interpreter = "C:/runs/python.exe"
    return View3dService(
        Store(tmp_path),  # type: ignore[arg-type]
        Bridge(MethodRegistry()),
        Worker(available),  # type: ignore[arg-type]
        preferences,
    )


def test_one_evaluation_opens_two_compare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setattr(
        api_view3d.subprocess,
        "Popen",
        lambda command, **options: started.append((command, options)),
    )
    view = service(tmp_path)
    view.open(OpenParams(run_id="r-1", evaluations=[1]))
    view.open(OpenParams(run_id="r-1", evaluations=[1, 2]))
    assert started == [
        (
            [
                "C:/runs/python.exe",
                "-m",
                "nastran_view",
                "D:/store/a",
                "--title",
                "r-1: evaluation 1",
            ],
            {"close_fds": True},
        ),
        (
            [
                "C:/runs/python.exe",
                "-m",
                "nastran_view",
                "D:/store/a",
                "--compare",
                "D:/store/b",
                "--title",
                "r-1: evaluations 1 and 2",
            ],
            {"close_fds": True},
        ),
    ]


def test_nothing_starts_without_nastran_view_or_a_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_view3d.subprocess, "Popen", lambda *a, **k: pytest.fail())
    with pytest.raises(BridgeError, match="not installed"):
        service(tmp_path, available=False).open(
            OpenParams(run_id="r-1", evaluations=[1])
        )
    with pytest.raises(BridgeError, match="evaluation 3 in D:/store"):
        service(tmp_path).open(OpenParams(run_id="r-1", evaluations=[1, 3]))
