"""The demos of the Library, found in the examples and opened as copies."""

from pathlib import Path

from gemseo_process_builder.core.demos import copy_demo
from gemseo_process_builder.core.demos import demos_folder
from gemseo_process_builder.core.demos import find_demos

EXAMPLES = Path(__file__).parents[3] / "examples"


def test_the_demos_are_the_scripts_saying_how_to_run_them() -> None:
    # In the repository; in the package once installed.
    assert demos_folder() == EXAMPLES
    demos = {demo.id: demo for demo in find_demos(EXAMPLES)}
    assert "sellar_mdf.py" in demos
    assert "external_code/external_code.py" in demos
    assert "demoBiLevel/demo_bilevel.py" in demos
    # Not the modules and programs the demos use.
    assert "demoBiLevel/economics.py" not in demos
    assert "external_code/solver.py" not in demos
    assert "wingBiLevel/wing_bilevel.py" in demos
    assert "wingBiLevel100k/wing_bilevel_100k.py" in demos
    assert len(demos) == 14
    bilevel = demos["demoBiLevel/demo_bilevel.py"]
    assert bilevel.title == "Sobieski bi-level study in several files"
    assert bilevel.summary.startswith("The bi-level optimization of the Sobieski")
    assert bilevel.in_folder
    assert demos["sellar_mdf.py"].title == "Sellar MDF"
    assert not demos["sellar_mdf.py"].in_folder


def test_a_demo_is_copied_once(tmp_path: Path) -> None:
    folder = tmp_path / "demos"
    (folder / "study" / "models").mkdir(parents=True)
    (folder / "study" / "models" / "trained.pkl").write_bytes(b"model")
    (folder / "study" / "helper.py").write_text("X = 1\n", "utf-8")
    (folder / "study" / "study.py").write_text(
        '"""A study.\n\nRun it with: python study.py\n"""\n', "utf-8"
    )
    (folder / "alone.py").write_text(
        '"""Alone.\n\nRun it with: python alone.py\n"""\n', "utf-8"
    )
    demos = {demo.id: demo for demo in find_demos(folder)}
    assert sorted(demos) == ["alone.py", "study/study.py"]
    copies = tmp_path / "copies"
    script = copy_demo(folder, demos["study/study.py"], copies)
    assert script == copies / "study" / "study.py"
    assert (copies / "study" / "helper.py").is_file()
    assert not (copies / "study" / "models").exists()  # Trained again by the demo.
    assert copy_demo(folder, demos["alone.py"], copies) == copies / "alone" / "alone.py"
    # Copied before: the changes of the user are kept.
    script.write_text("# Changed.\n", "utf-8")
    assert copy_demo(folder, demos["study/study.py"], copies) == script
    assert script.read_text("utf-8") == "# Changed.\n"
