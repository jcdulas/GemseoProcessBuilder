import io
import shutil
from typing import Any

import pytest
from builders import component
from builders import project
from golden_projects import example

from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.server import WorkerError
from gemseo_process_builder.workers.xdsm_methods import build
from gemseo_process_builder.workers.xdsm_methods import capabilities


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


def edges(diagram: dict[str, Any]) -> dict[tuple[str, str], str]:
    names = {node["id"]: node["name"] for node in diagram["nodes"]}
    names["_U_"] = "user"
    return {(names[e["from"]], names[e["to"]]): e["name"] for e in diagram["edges"]}


def test_sellar_mdf() -> None:
    diagrams = build(generate(example("sellar_mdf"), "n-optimizer").source)
    root = diagrams["root"]
    assert [(node["name"], node["type"]) for node in root["nodes"]] == [
        ("Optimizer", "optimization"),
        ("MDAGaussSeidel", "mda"),
        ("Sellar1", "analysis"),
        ("Sellar2", "analysis"),
        ("SellarSystem", "analysis"),
    ]
    found = edges(root)
    assert found[("Sellar1", "Sellar2")] == "y_1"
    assert found[("Sellar2", "MDAGaussSeidel")] == "y_2"
    assert found[("Optimizer", "Sellar1")] == "x_1, x_shared"
    assert root["workflow"] == ["_U_", ["Opt", ["Dis1", ["Dis2", "Dis3", "Dis4"]]]]


def test_bilevel_has_one_diagram_per_sub_scenario() -> None:
    diagrams = build(generate(example("sobieski_bilevel"), "n-system").source)
    assert sorted(diagrams) == [
        "AerodynamicsOptimizer_scn-1-2",
        "PropulsionOptimizer_scn-1-1",
        "StructureOptimizer_scn-1-3",
        "root",
    ]
    subs = [node for node in diagrams["root"]["nodes"] if node["type"] == "mdo"]
    assert [node["subxdsm"] for node in subs] == [
        "PropulsionOptimizer_scn-1-1",
        "AerodynamicsOptimizer_scn-1-2",
        "StructureOptimizer_scn-1-3",
    ]


def test_processes_have_no_xdsm() -> None:
    analytic = component("A", ["x"], ["y"], config={"expressions": {"y": "x"}})
    with pytest.raises(WorkerError, match="select one of these drivers"):
        build(generate(project(analytic)).source)


def test_broken_scenarios_are_reported() -> None:
    sellar = example("sellar_mdf")
    optimizer = sellar.find("n-optimizer")
    optimizer.config["constraints"] = [{"variable": "c_9"}]  # type: ignore[union-attr]
    with pytest.raises(WorkerError, match="c_9"):
        build(generate(sellar, "n-optimizer").source)


def test_pdf_needs_latex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    result = capabilities()
    assert not result["pdf"]
    assert "LaTeX" in result["reason"] or "pyXDSM" in result["reason"]
