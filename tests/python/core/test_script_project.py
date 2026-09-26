"""Projects saved as GEMSEO scripts: merging, side file, carrying over."""

from pathlib import Path

from builders import component
from builders import driver
from builders import project
from golden_projects import example

from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.codegen.generator import project_script
from gemseo_process_builder.codegen.generator import project_target
from gemseo_process_builder.core.model import NodeLayout
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import RunRef
from gemseo_process_builder.core.script_project import carry_over
from gemseo_process_builder.core.script_project import merge_script
from gemseo_process_builder.core.script_project import read_side
from gemseo_process_builder.core.script_project import side_data
from gemseo_process_builder.core.script_project import side_file

GENERATED = generate(example("sellar_mdf"), "n-optimizer").source


def test_the_code_added_by_the_user_is_kept() -> None:
    existing = GENERATED.replace(
        'if __name__ == "__main__":',
        "import json\n\n\n"
        "# My post-processing.\n"
        "def summary(scenario):\n"
        "    return json.dumps(scenario.optimization_result.x_opt.tolist())\n\n\n"
        "THRESHOLD = 3.0\n\n\n"
        'if __name__ == "__main__":',
    )
    merged = merge_script(GENERATED, existing)
    assert (merged.kept, merged.replaced) == (["summary"], False)
    source = merged.source
    assert "import json\n" in source
    assert "# My post-processing.\ndef summary(scenario):" in source
    assert "THRESHOLD = 3.0" in source
    # Before the functions of the application, once each.
    assert source.index("def summary") < source.index("def build_disciplines")
    assert source.count("def build_scenario") == 1
    assert source.count('if __name__ == "__main__":') == 1
    compile(source, "sellar.py", "exec")
    # Saving again changes nothing.
    assert merge_script(GENERATED, source).source == source


def test_a_script_written_by_hand_keeps_its_definitions_only() -> None:
    existing = (
        '"""My study."""\n'
        "from gemseo import create_scenario\n\n\n"
        "def area(span=1.0):\n    area = span\n    return area\n\n\n"
        "scenario = create_scenario([], 'area', None)\n"
        "scenario.execute(algo_name='SLSQP')\n"
    )
    merged = merge_script(GENERATED, existing)
    assert (merged.kept, merged.replaced) == (["area"], True)
    assert "def area(span=1.0):" in merged.source
    assert "scenario.execute(algo_name='SLSQP')" not in merged.source
    assert merge_script(GENERATED, "def (").replaced


def test_the_side_file_says_whether_the_script_changed(tmp_path: Path) -> None:
    script = tmp_path / "sellar.py"
    script.write_text(GENERATED, encoding="utf-8")
    assert side_file(script) == tmp_path / ".sellar.gpb.json"
    assert read_side(script) is None
    side_file(script).write_text(side_data({"root": {}}, GENERATED), encoding="utf-8")
    assert read_side(script) == ({"root": {}}, True)
    script.write_text(GENERATED + "\n# Edited.\n", encoding="utf-8")
    assert read_side(script) == ({"root": {}}, False)


def test_a_project_read_again_keeps_ids_layout_units_and_runs() -> None:
    old = project(driver("Opt", "optimization", component("Area", ["span"], ["area"])))
    old.root.children[0].children[0].ports[0].unit = "m"
    old.layout.nodes["n-Area"] = NodeLayout(x=120.0, y=40.0)
    old.runs = [RunRef(id="r-1", driver="n-Opt", run_path="runs/r-1")]
    new = project(
        driver("Opt", "optimization", component("Area", ["span"], ["area"])),
        component("Other"),
    )
    area = new.root.children[0].children[0]
    area.id = "n-read-0"
    area.ports = [Port(local_name="span", direction="in"), *area.ports[1:]]
    other = new.root.children[1]
    other.id = "n-Opt"  # Read with an id the old project used.
    carry_over(new, old)
    assert area.id == "n-Area"
    assert new.layout.nodes["n-Area"].x == 120.0
    assert area.ports[0].unit == "m"
    assert new.runs == old.runs
    assert other.id != "n-Opt"


def test_the_script_of_a_project_uses_its_own_definitions(tmp_path: Path) -> None:
    script = tmp_path / "wing.py"
    function = component("Area", ["span"], ["area"], kind="python_function")
    function.config = {"module_path": str(script), "function": "wing_area"}
    elsewhere = component("Lift", ["area"], ["lift"], kind="python_function")
    elsewhere.config = {"module_path": str(tmp_path / "lift.py"), "function": "lift"}
    p = project(function, elsewhere)
    assert project_target(p) == p.root.id
    source = project_script(p, script)
    assert "AutoPyDiscipline(wing_area, " in source
    assert "Run it with: python wing.py" in source
    assert "from wing import" not in source  # Not imported from itself.
    assert "from lift import lift" in source
    single = project(driver("Opt", "optimization", component("A", ["x"], ["y"])))
    assert project_target(single) == "n-Opt"
