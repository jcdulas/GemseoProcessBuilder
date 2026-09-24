"""Golden tests of the generated scripts.

Each project of ``tests/python/golden_projects.py`` is compared with the script
stored in ``golden/``. After a deliberate change of the generator, rewrite them with
``pytest tests/python/codegen --update-golden`` and review the diff by hand:
the golden files are what users read.
"""

import json
from datetime import date
from pathlib import Path

import pytest
from builders import component
from builders import driver
from builders import project
from golden_projects import GOLDEN_PROJECTS
from golden_projects import TARGETS

from gemseo_process_builder.codegen.generator import CodegenError
from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.codegen.generator import script_file_name
from gemseo_process_builder.codegen.generator import write_script

GOLDEN = Path(__file__).parent / "golden"
DATE = date(2026, 1, 1)


def generate_golden(name: str) -> str:
    project = GOLDEN_PROJECTS[name]()
    return generate(project, TARGETS.get(name), f"{name}.gpb.json", DATE).source


@pytest.mark.parametrize("name", GOLDEN_PROJECTS)
def test_golden_script(name: str, request: pytest.FixtureRequest) -> None:
    source = generate_golden(name)
    path = GOLDEN / f"{name}.py"
    if request.config.getoption("--update-golden"):
        path.write_text(source, encoding="utf-8", newline="\n")
    assert source == path.read_text(encoding="utf-8")


def test_mapping_names_the_discipline_of_each_component() -> None:
    script = generate(GOLDEN_PROJECTS["sellar_mda"](), "n-SellarMDA")
    assert script.mapping == {
        "target": "n-SellarMDA",
        "kind": "process",
        "disciplines": {
            "n-Sellar1": "Sellar1",
            "n-Sellar2": "Sellar2",
            "n-SellarSystem": "SellarSystem",
        },
        "variables": {
            "sellar1": "n-Sellar1",
            "sellar2": "n-Sellar2",
            "sellar_system": "n-SellarSystem",
        },
    }


def test_write_script_adds_the_mapping_sidecar(tmp_path: Path) -> None:
    script = generate(GOLDEN_PROJECTS["analytic_chain"]())
    write_script(script, tmp_path / "panel.py")
    assert (tmp_path / "panel.py").read_text(encoding="utf-8") == script.source
    sidecar = json.loads((tmp_path / "panel.gpb-map.json").read_text("utf-8"))
    assert sidecar["disciplines"] == {"n-Area": "Area", "n-Cost": "Cost"}


def test_chain_runs_disciplines_after_their_inputs() -> None:
    source = generate_golden("analytic_chain")
    assert source.index("area = Analytic") < source.index("cost = Analytic")


def test_script_file_name() -> None:
    sellar = GOLDEN_PROJECTS["sellar_mda"]()
    assert script_file_name(sellar, sellar.root.id) == "sellar.py"
    assert script_file_name(sellar, "n-SellarMDA") == "sellar_sellar_mda.py"


def test_variables_never_shadow_the_functions_of_the_script() -> None:
    node = component("main", ["x"], ["y"], config={"expressions": {"y": "x"}})
    source = generate(project(node)).source
    assert "    main_2 = AnalyticDiscipline" in source


@pytest.mark.parametrize(
    ("built", "target", "message"),
    [
        (project(), None, "Model is empty"),
        (project(driver("Optimizer", "optimization")), "n-Optimizer", "is empty"),
        (
            project(driver("Optimizer", "optimization", component("A", ["x"], ["y"]))),
            "n-Optimizer",
            "choose an objective first",
        ),
        (project(component("A", ["x"], ["y"])), "n-A", "Only the model"),
        (
            project(component("A", ["x"], ["y"], kind="executable")),
            None,
            "executable components",
        ),
    ],
)
def test_unsupported_projects_are_explained(
    built: object, target: str | None, message: str
) -> None:
    with pytest.raises(CodegenError, match=message):
        generate(built, target)  # type: ignore[arg-type]
