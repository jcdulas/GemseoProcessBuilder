"""The golden scripts run and give the results of hand-written GEMSEO code."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from gemseo import create_mda
from gemseo.problems.mdo.sellar.sellar_1 import Sellar1
from gemseo.problems.mdo.sellar.sellar_2 import Sellar2
from gemseo.problems.mdo.sellar.sellar_system import SellarSystem
from numpy.testing import assert_allclose

GOLDEN = Path(__file__).parent / "golden"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"golden_{name}", GOLDEN / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sellar_mda_matches_hand_written_gemseo() -> None:
    process = load("sellar_mda").build_process()
    reference = create_mda(
        "MDAChain",
        [Sellar1(), Sellar2(), SellarSystem()],
        tolerance=1e-10,
        max_mda_iter=50,
    )
    results = process.execute()
    expected = reference.execute()
    for name in ("y_1", "y_2", "obj", "c_1", "c_2"):
        assert_allclose(results[name], expected[name], rtol=1e-8)


@pytest.mark.parametrize(
    ("name", "line"),
    [
        ("analytic_chain", "cost = [5.5]"),
        ("parallel_assembly", "lift = [0.]"),
        ("remapped_link", "stress = [3.]"),
        ("isolated_instances", "total_mass = [31200.]"),
    ],
)
def test_main_prints_the_results(
    name: str, line: str, capsys: pytest.CaptureFixture[str]
) -> None:
    load(name).main()
    assert line in capsys.readouterr().out.splitlines()
