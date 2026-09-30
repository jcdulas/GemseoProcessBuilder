from pathlib import Path
from typing import Any

import pytest

from gemseo_process_builder.app.api_postproc import PostprocController
from gemseo_process_builder.app.api_postproc import ResultParams
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import MethodRegistry


class FakeStore:
    def __init__(self, folders: dict[str, Path]) -> None:
        self.folders = folders

    def folder_of(self, run_id: str) -> Path | None:
        return self.folders.get(run_id)


@pytest.fixture
def run_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "r-1"
    (folder / "postproc" / "OptHistoryView-1").mkdir(parents=True)
    (folder / "keep.txt").write_text("keep")
    return folder


@pytest.fixture
def controller(run_folder: Path) -> PostprocController:
    store: Any = FakeStore({"r-1": run_folder})
    worker: Any = None
    return PostprocController(store, Bridge(MethodRegistry()), worker)


def test_delete_removes_the_output(
    controller: PostprocController, run_folder: Path
) -> None:
    controller.delete(ResultParams(id="r-1", result="OptHistoryView-1"))
    assert not (run_folder / "postproc" / "OptHistoryView-1").exists()
    assert (run_folder / "keep.txt").exists()


@pytest.mark.parametrize("result", ["..", "../..", "a/b", "", "missing"])
def test_delete_refuses_other_folders(
    controller: PostprocController, run_folder: Path, result: str
) -> None:
    with pytest.raises(BridgeError):
        controller.delete(ResultParams(id="r-1", result=result))
    assert (run_folder / "keep.txt").exists()


def test_unknown_run_is_not_found(controller: PostprocController) -> None:
    with pytest.raises(BridgeError, match="not in the project"):
        controller.delete(ResultParams(id="r-9", result="OptHistoryView-1"))
