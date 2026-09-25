import io
import json
import shutil
from pathlib import Path

import pytest

from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.postproc_methods import available
from gemseo_process_builder.workers.postproc_methods import describe
from gemseo_process_builder.workers.postproc_methods import results
from gemseo_process_builder.workers.postproc_methods import run
from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.server import CancelledError
from gemseo_process_builder.workers.server import RequestContext
from gemseo_process_builder.workers.server import WorkerError

FIXTURE = Path(__file__).parent.parent / "results" / "fixtures" / "sellar_run"


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


@pytest.fixture
def run_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "run"
    shutil.copytree(FIXTURE, folder)
    return folder


def context() -> RequestContext:
    return RequestContext("r1", EventChannel(io.StringIO()))


def set_algorithm(folder: Path, algorithm: str) -> None:
    path = folder / "run.json"
    info = json.loads(path.read_text(encoding="utf-8"))
    info["algorithm"] = algorithm
    path.write_text(json.dumps(info), encoding="utf-8")


def test_optimization_runs_get_every_post_processing(run_folder: Path) -> None:
    set_algorithm(run_folder, "SLSQP")
    names = available(run_folder)
    assert {"OptHistoryView", "ConstraintsHistory", "ScatterPlotMatrix"} <= set(names)
    assert "Animation" not in names


def test_doe_runs_get_the_sample_post_processings(run_folder: Path) -> None:
    set_algorithm(run_folder, "LHS")
    names = available(run_folder)
    assert "ScatterPlotMatrix" in names
    assert "OptHistoryView" not in names


def test_schemas_leave_out_the_output_settings(run_folder: Path) -> None:
    items = {item["name"]: item for item in describe(run_folder)}
    schema = items["OptHistoryView"]["schema"]
    assert "variable_names" in schema["properties"]
    assert "file_extension" not in schema["properties"]
    assert "show" not in schema["properties"]
    assert items["OptHistoryView"]["description"]


def test_opt_history_view_saves_svg_files(run_folder: Path) -> None:
    result = run(run_folder, "OptHistoryView", {}, context())
    assert result["files"]
    assert all(name.startswith(f"postproc/{result['id']}/") for name in result["files"])
    assert all(name.endswith(".svg") for name in result["files"])
    assert (run_folder / result["files"][0]).read_text(encoding="utf-8").strip()
    assert [item["id"] for item in results(run_folder)] == [result["id"]]


def test_unknown_post_processing_is_refused(run_folder: Path) -> None:
    with pytest.raises(WorkerError, match="No post-processing"):
        run(run_folder, "Missing", {}, context())


def test_invalid_settings_are_refused(run_folder: Path) -> None:
    with pytest.raises(WorkerError, match="Invalid settings"):
        run(run_folder, "OptHistoryView", {"obj_relative": "maybe"}, context())


def test_failure_leaves_no_output(run_folder: Path) -> None:
    with pytest.raises(WorkerError, match="BasicHistory failed"):
        run(run_folder, "BasicHistory", {"variable_names": ["missing"]}, context())
    assert not list((run_folder / "postproc").iterdir())


def test_cancelled_request_writes_nothing(run_folder: Path) -> None:
    cancelled = context()
    cancelled.cancel()
    with pytest.raises(CancelledError):
        run(run_folder, "OptHistoryView", {}, cancelled)
    assert results(run_folder) == []
