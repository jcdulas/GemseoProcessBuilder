import io

import pytest
from builders import component
from builders import project
from golden_projects import example

from gemseo_process_builder.app.validation_service import dry_run_targets
from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.workers.codegen_methods import dry_run
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


def check(p: Project, target: str | None = None) -> list[dict]:
    script = generate(p, target)
    return dry_run(script.source, script.mapping)


def test_valid_script() -> None:
    assert check(example("sellar_mdf"), "n-optimizer") == []


def test_wrong_constraint_is_attached_to_the_driver() -> None:
    sellar = example("sellar_mdf")
    optimizer = sellar.find("n-optimizer")
    optimizer.config["constraints"] = [{"variable": "c_9"}]  # type: ignore[union-attr]
    (issue,) = check(sellar, "n-optimizer")
    assert issue["node"] == "n-optimizer"
    assert "c_9" in issue["message"]


def test_error_in_a_constructor_is_attached_to_its_component() -> None:
    sellar = example("sellar_mdf")
    sellar1 = sellar.find("n-sellar1")
    sellar1.config["init_args"] = {"bogus": 1}  # type: ignore[union-attr]
    (issue,) = check(sellar, "n-optimizer")
    assert issue["node"] == "n-sellar1"
    assert issue["message"].startswith("TypeError")


def test_process_targets_are_built_too() -> None:
    broken = component("Broken", ["x"], ["y"], config={"expressions": {"y": "x**"}})
    (issue,) = check(project(broken))
    assert issue["node"] == "n-Broken"


def test_dry_run_targets() -> None:
    sellar = example("sellar_mdf")
    assert [target.id for target in dry_run_targets(sellar)] == ["n-optimizer"]
    model = project(component("A", ["x"], ["y"]))
    assert [target.id for target in dry_run_targets(model)] == ["n-root"]
