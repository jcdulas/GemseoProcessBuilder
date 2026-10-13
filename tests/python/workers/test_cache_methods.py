"""File caches: served to a later run, counted, cleared, read back (SPEC § 8.7)."""

import io
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from gemseo.core.discipline import Discipline
from golden_projects import cached_disciplines

from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.workers.cache_methods import _clear
from gemseo_process_builder.workers.cache_methods import _inspect
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.script_reader import read_script
from gemseo_process_builder.workers.server import WorkerError


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


pytestmark = pytest.mark.usefixtures("in_process_caches")


class Counted(Discipline):
    """``y = 2 x``, counting its executions."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.io.input_grammar.update_from_data({"x": np.zeros(1)})
        self.io.output_grammar.update_from_data({"y": np.zeros(1)})
        self.io.input_grammar.defaults = {"x": np.zeros(1)}
        self.executions = 0

    def _run(self, input_data: Mapping[str, Any]) -> dict[str, Any]:
        self.executions += 1
        return {"y": 2 * input_data["x"]}


def cached(name: str, file: Path, node: str) -> Counted:
    discipline = Counted(name)
    discipline.set_cache(
        Discipline.CacheType.HDF5, hdf_file_path=file, hdf_node_path=node
    )
    return discipline


def test_a_later_run_is_served_by_the_file(tmp_path: Path) -> None:
    file = tmp_path / "study.h5"
    first = cached("Sizing", file, "Study/Sizing")
    other = cached("Loads", file, "Study/Loads")
    for value in (1.0, 2.0):
        first.execute({"x": np.array([value])})
    other.execute({"x": np.array([5.0])})
    assert (first.executions, other.executions) == (2, 1)
    # Another run builds the discipline again on the same file.
    again = cached("Sizing", file, "Study/Sizing")
    result = again.execute({"x": np.array([1.0])})
    assert again.executions == 0
    assert result["y"][0] == pytest.approx(2.0)
    # Two nodes in one file: counted and cleared one by one.
    assert _inspect({"file": str(file), "node": "Study/Sizing"}, None) == {
        "exists": True,
        "entries": 2,
    }
    assert _inspect({"file": str(file), "node": "Study/Loads"}, None)["entries"] == 1
    assert _clear({"file": str(file), "node": "Study/Sizing"}, None) == {"removed": 2}
    assert _inspect({"file": str(file), "node": "Study/Sizing"}, None) == {
        "exists": False,
        "entries": 0,
    }
    assert _inspect({"file": str(file), "node": "Study/Loads"}, None)["entries"] == 1
    assert _clear({"file": str(file), "node": "Study/Sizing"}, None) == {"removed": 0}
    missing = {"file": str(tmp_path / "none.h5"), "node": "A"}
    assert _inspect(missing, None) == {"exists": False, "entries": 0}
    with pytest.raises(WorkerError, match="A cache file and a node"):
        _inspect({"file": str(file)}, None)


def test_the_script_reader_gives_the_caches_back(tmp_path: Path) -> None:
    model = cached_disciplines()
    file = tmp_path / "caches" / "thermal.h5"
    model.find("n-Sink").config["cache"]["file"] = str(file)  # type: ignore[union-attr]
    model.find("n-Panel").cache["file"] = str(file)  # type: ignore[union-attr]
    script = tmp_path / "cached.py"
    script.write_text(generate(model).source, "utf-8")
    read = read_script(script)
    children = {child["name"]: child for child in read["project"]["root"]["children"]}
    assert children["Source"]["config"]["cache"] == {"type": "none"}
    assert children["Sink"]["config"]["cache"] == {
        "type": "hdf5",
        "file": str(file.resolve()),
        "node": "Sink",
    }
    assert children["Panel"]["cache"]["node"] == "Panel"
    area = next(c for c in children["Panel"]["children"] if c["name"] == "Area")
    assert area["config"]["cache"] == {"type": "memory", "tolerance": 1e-9}
    assert "cache" not in children["Panel"]["children"][1]["config"]
    # Reading created no cache file.
    assert not file.exists()
