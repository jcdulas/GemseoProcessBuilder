"""Python files of discipline classes written by the application."""

import pytest

from gemseo_process_builder.core.discipline_file import DisciplineFileError
from gemseo_process_builder.core.discipline_file import FileVariable
from gemseo_process_builder.core.discipline_file import class_name_for
from gemseo_process_builder.core.discipline_file import new_module
from gemseo_process_builder.core.discipline_file import read_variables
from gemseo_process_builder.core.discipline_file import write_variables

WING = [
    FileVariable("span", "in", [10.0]),
    FileVariable("chord", "in", [2.0, 3.0]),
    FileVariable("area", "out"),
]


def test_a_new_module_reads_its_inputs_and_returns_its_outputs() -> None:
    source = new_module("Wing", "The area of a wing.", WING)
    assert '"""The area of a wing: a GEMSEO discipline.' in source
    assert "class Wing(Discipline):" in source
    assert '    INPUTS = {"span": [10.0], "chord": [2.0, 3.0]}' in source
    assert '    OUTPUTS = ["area"]' in source
    assert '        span = input_data["span"]' in source
    assert "        area = array([0.0])" in source
    assert '        return {"area": area}' in source
    compile(source, "wing.py", "exec")
    assert read_variables(source, "Wing") == WING


def test_rewriting_the_variables_keeps_the_code_of_the_user() -> None:
    source = new_module("Wing", "", WING).replace(
        "area = array([0.0])", "area = span * chord.sum()  # My formula."
    )
    variables = [*WING, FileVariable("sweep", "in", [0.5]), FileVariable("lift", "out")]
    written = write_variables(source, "Wing", variables)
    assert "area = span * chord.sum()  # My formula." in written
    assert read_variables(written, "Wing") == [
        variables[0],
        variables[1],
        variables[3],
        variables[2],
        variables[4],
    ]
    # Only the block changed.
    assert (
        written.replace(
            '"chord": [2.0, 3.0], "sweep": [0.5]}', '"chord": [2.0, 3.0]}'
        ).replace('["area", "lift"]', '["area"]')
        == source
    )


def test_long_blocks_take_one_line_per_variable() -> None:
    many = [FileVariable(f"variable_{i}", "in", [float(i)]) for i in range(8)]
    written = new_module("Many", "", [*many, FileVariable("y", "out")])
    assert '        "variable_7": [7.0],' in written
    assert read_variables(written, "Many")[7] == many[7]


def test_classes_declaring_their_variables_in_their_code() -> None:
    source = "class Mine:\n    def __init__(self):\n        pass\n"
    assert read_variables(source, "Mine") is None
    with pytest.raises(DisciplineFileError, match="edit them in the code"):
        write_variables(source, "Mine", WING)
    with pytest.raises(DisciplineFileError, match="no class Other"):
        read_variables(source, "Other")
    with pytest.raises(DisciplineFileError, match="syntax error, line 1"):
        read_variables("class (:", "Mine")


@pytest.mark.parametrize(
    ("variables", "message"),
    [
        ([FileVariable("2x", "in", [1.0]), FileVariable("y", "out")], "not a valid"),
        (
            [FileVariable("lambda", "in", [1.0]), FileVariable("y", "out")],
            "not a valid",
        ),
        ([FileVariable("x", "in", [1.0]), FileVariable("x", "out")], "twice"),
        ([FileVariable("x", "in", []), FileVariable("y", "out")], "default value"),
        ([FileVariable("x", "in", [1.0])], "at least one output"),
    ],
)
def test_invalid_variables(variables: list[FileVariable], message: str) -> None:
    with pytest.raises(DisciplineFileError, match=message):
        new_module("Wing", "", variables)


def test_class_names() -> None:
    assert class_name_for("my wing 2") == "MyWing2"
    assert class_name_for("2 wings") == "Discipline2Wings"
    assert class_name_for("") == "Discipline"
