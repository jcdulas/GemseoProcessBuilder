"""Test runs of wrappers from their editor."""

import io
from pathlib import Path

import pytest

from gemseo_process_builder.app.api_executable import editable_spec
from gemseo_process_builder.workers.executable_methods import test_run as run_once
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.server import WorkerError

EXAMPLE = Path(__file__).parents[3] / "examples" / "external_code"


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


def test_a_test_run_reports_outputs_and_keeps_the_folder(tmp_path: Path) -> None:
    spec = editable_spec(EXAMPLE / "solver.gpbwrap.json")["spec"]
    spec["workdir_root"] = str(tmp_path)
    report = run_once(spec, {"x": [1.0], "y": [2.0]}, "")
    assert report["error"] == ""
    assert report["returncode"] == 0
    assert set(report["outputs"]) == {"f", "g"}
    assert Path(report["workdir"], "input.txt").is_file()
    assert "solver.py" in report["command"]


def test_a_failing_run_reports_its_output(tmp_path: Path) -> None:
    spec = {
        "name": "Fails",
        "command": '{python} -c "import sys; print(42); sys.exit(3)"',
        "outputs": [{"name": "f"}],
        "workdir_root": str(tmp_path),
    }
    report = run_once(spec, {}, "")
    assert "returned 3" in report["error"]
    assert report["returncode"] == 3
    assert report["stdout"].strip() == "42"
    assert Path(report["workdir"]).is_dir()


def test_invalid_specs_are_refused() -> None:
    with pytest.raises(WorkerError, match="Invalid wrapper"):
        run_once({"name": "A"}, {}, "")
