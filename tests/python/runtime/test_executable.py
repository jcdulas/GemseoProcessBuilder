"""Runs of external codes: the example solver, and quick failing commands."""

from pathlib import Path
from typing import Any

import pytest
from numpy.testing import assert_allclose

from gemseo_process_builder.runtime.executable import ExecutableDiscipline
from gemseo_process_builder.runtime.executable import ExecutableError
from gemseo_process_builder.runtime.spec import ExecutableSpec
from gemseo_process_builder.runtime.spec import PortSpec
from gemseo_process_builder.runtime.spec import load_descriptor
from gemseo_process_builder.runtime.spec import save_descriptor

EXAMPLE = Path(__file__).parents[3] / "examples" / "external_code"


def test_the_example_solver_runs(tmp_path: Path) -> None:
    solver = ExecutableDiscipline.from_descriptor(EXAMPLE / "solver.gpbwrap.json")
    solver.spec.workdir_root = str(tmp_path)
    outputs = solver.execute({"x": [1.5], "y": [0.5]})
    assert_allclose(outputs["f"], [0.25 + 2.25 + 1])
    assert_allclose(outputs["g"], [-0.5])
    # A successful run leaves no working folder behind.
    assert list(tmp_path.iterdir()) == []


def spec(command: str, **fields: Any) -> ExecutableSpec:
    return ExecutableSpec(
        name="Code",
        command=command,
        inputs=[PortSpec(name="x", default=1.0)],
        outputs=[PortSpec(name="y")],
        **fields,
    )


def run(tmp_path: Path, command: str, **fields: Any) -> ExecutableDiscipline:
    discipline = ExecutableDiscipline(
        spec(command, workdir_root=str(tmp_path), **fields)
    )
    discipline.execute()
    return discipline


def test_unexpected_return_code(tmp_path: Path) -> None:
    with pytest.raises(ExecutableError, match="the command returned 3"):
        run(tmp_path, "exit 3")
    # On error, the working folder is kept for investigation.
    assert len(list(tmp_path.iterdir())) == 1


def test_error_pattern_in_the_output(tmp_path: Path) -> None:
    with pytest.raises(ExecutableError, match="'ERROR: diverged'"):
        run(tmp_path, "echo ERROR: diverged", error_patterns=["ERROR.*"])


def test_missing_output_file(tmp_path: Path) -> None:
    rule = {"kind": "key_value", "variable": "y", "file": "out.txt", "key": "y"}
    with pytest.raises(ExecutableError, match=r"out.txt of y was not produced"):
        run(tmp_path, "echo done", rules=[rule])


def test_output_read_from_the_standard_output(tmp_path: Path) -> None:
    rule = {"kind": "key_value", "variable": "y", "key": "y"}
    discipline = run(tmp_path, "echo y = 4.5", rules=[rule], retention="always")
    assert_allclose(discipline.io.data["y"], [4.5])
    assert discipline.last_workdir is not None
    assert discipline.last_workdir.is_dir()


def test_timeout_kills_the_command(tmp_path: Path) -> None:
    command = '{python} -c "import time; time.sleep(10)"'
    with pytest.raises(ExecutableError, match=r"did not finish within 0.3 s"):
        run(tmp_path, command, timeout=0.3)


def test_descriptor_round_trip(tmp_path: Path) -> None:
    original, _ = load_descriptor(EXAMPLE / "solver.gpbwrap.json")
    path = tmp_path / "copy.gpbwrap.json"
    save_descriptor(original, path)
    copy, folder = load_descriptor(path)
    assert copy == original
    assert folder == tmp_path
    with pytest.raises(ValueError, match="not a valid wrapper descriptor"):
        path.write_text("{}")
        load_descriptor(path)
