"""Python files of discipline classes written by the application."""

import pytest

from gemseo_process_builder.core.discipline_file import DisciplineFileError
from gemseo_process_builder.core.discipline_file import FileVariable
from gemseo_process_builder.core.discipline_file import class_name_for
from gemseo_process_builder.core.discipline_file import default_code
from gemseo_process_builder.core.discipline_file import new_module
from gemseo_process_builder.core.discipline_file import read_variables
from gemseo_process_builder.core.discipline_file import write_variables

WING = [
    FileVariable("span", "in", values=[10.0]),
    FileVariable("chord", "in", shape=[2], values=[2.0, 3.0]),
    FileVariable("area", "out"),
]


def test_a_new_module_reads_its_inputs_and_returns_its_outputs() -> None:
    source = new_module("Wing", "The area of a wing.", WING)
    assert '"""The area of a wing: a GEMSEO discipline.' in source
    assert "class Wing(Discipline):" in source
    assert "    default_grammar_type = Discipline.GrammarType.SIMPLE" in source
    assert "from numpy import array, ndarray" in source
    assert '    INPUTS = {"span": array([10.0]), "chord": array([2.0, 3.0])}' in source
    assert '    OUTPUTS = ["area"]' in source
    assert '        span = input_data["span"]' in source
    assert "        area = array([0.0])" in source
    assert '        return {"area": area}' in source
    compile(source, "wing.py", "exec")
    assert read_variables(source, "Wing") == WING


@pytest.mark.parametrize(
    ("variable", "code"),
    [
        (FileVariable("x", "in", fill=0.5), "array([0.5])"),
        (FileVariable("x", "in", shape=[100_000], fill=0.5), "full(100_000, 0.5)"),
        (FileVariable("x", "in", shape=[3, 4], fill=1.0), "full((3, 4), 1.0)"),
        (
            FileVariable("x", "in", "int", [2, 2], values=[1, 2, 3, 4]),
            "array([1, 2, 3, 4], dtype=int).reshape(2, 2)",
        ),
        (
            FileVariable("x", "in", "complex", [5], fill=0.0),
            "full(5, 0.0, dtype=complex)",
        ),
        (
            FileVariable("n", "in", "int", [20_000], fill=12_000),
            "full(20_000, 12_000, dtype=int)",
        ),
    ],
)
def test_default_values_as_numpy_code(variable: FileVariable, code: str) -> None:
    assert default_code(variable) == code
    source = new_module("Big", "", [variable, FileVariable("y", "out")])
    compile(source, "big.py", "exec")
    (read, _) = read_variables(source, "Big")
    assert read == variable or (
        # A single value is read back as the values of a one-element array.
        variable.shape == [1] and read.values == [variable.fill]
    )


def test_rewriting_the_variables_keeps_the_code_of_the_user() -> None:
    source = new_module("Wing", "", WING).replace(
        "area = array([0.0])", "area = span * chord.sum()  # My formula."
    )
    variables = [
        *WING,
        FileVariable("mesh", "in", shape=[1000], fill=0.1),
        FileVariable("lift", "out"),
    ]
    written = write_variables(source, "Wing", variables)
    assert "area = span * chord.sum()  # My formula." in written
    # full is now needed: it is imported.
    assert "from numpy import array, full, ndarray" in written
    assert [v.name for v in read_variables(written, "Wing")] == [
        "span",
        "chord",
        "mesh",
        "area",
        "lift",
    ]
    assert read_variables(written, "Wing")[2].fill == 0.1


def test_files_written_before_numpy_defaults_are_still_read() -> None:
    source = (
        "from numpy import array\n\n\nclass Old:\n"
        "    # >>> Variables: old\n"
        '    INPUTS = {"span": [10.0], "chord": [2.0, 3.0]}\n'
        '    OUTPUTS = ["area"]\n'
        "    # <<< Variables\n"
    )
    assert read_variables(source, "Old") == WING
    written = write_variables(
        source, "Old", [*WING, FileVariable("m", "in", shape=[50], fill=0.0)]
    )
    assert written.startswith("from numpy import array, full\n")


def test_long_blocks_take_one_line_per_variable() -> None:
    many = [FileVariable(f"variable_{i}", "in", fill=float(i)) for i in range(8)]
    written = new_module("Many", "", [*many, FileVariable("y", "out")])
    assert '        "variable_7": array([7.0]),' in written


def test_classes_declaring_their_variables_in_their_code() -> None:
    source = "class Mine:\n    def __init__(self):\n        pass\n"
    assert read_variables(source, "Mine") is None
    with pytest.raises(DisciplineFileError, match="edit them in the code"):
        write_variables(source, "Mine", WING)
    with pytest.raises(DisciplineFileError, match="no class Other"):
        read_variables(source, "Other")
    with pytest.raises(DisciplineFileError, match="syntax error, line 1"):
        read_variables("class (:", "Mine")
    unknown = (
        "class Mine:\n    # >>> Variables\n    INPUTS = {'x': zeros(3)}\n"
        "    OUTPUTS = ['y']\n    # <<< Variables\n"
    )
    with pytest.raises(DisciplineFileError, match="edit it in the code"):
        read_variables(unknown, "Mine")


@pytest.mark.parametrize(
    ("variables", "message"),
    [
        ([FileVariable("2x", "in", fill=1.0), FileVariable("y", "out")], "not a valid"),
        (
            [FileVariable("lambda", "in", fill=1.0), FileVariable("y", "out")],
            "not a valid",
        ),
        ([FileVariable("x", "in", fill=1.0), FileVariable("x", "out")], "twice"),
        ([FileVariable("x", "in"), FileVariable("y", "out")], "default value"),
        (
            [
                FileVariable("x", "in", shape=[3], values=[1.0, 2.0]),
                FileVariable("y", "out"),
            ],
            "2 values for 3 elements",
        ),
        (
            [FileVariable("x", "in", shape=[0], fill=1.0), FileVariable("y", "out")],
            "positive sizes",
        ),
        ([FileVariable("x", "in", fill=1.0)], "at least one output"),
        (
            [
                FileVariable("x", "in", shape=[21], values=[0.0] * 21),
                FileVariable("y", "out"),
            ],
            "more than 20 values",
        ),
    ],
)
def test_invalid_variables(variables: list[FileVariable], message: str) -> None:
    with pytest.raises(DisciplineFileError, match=message):
        new_module("Wing", "", variables)


def test_class_names() -> None:
    assert class_name_for("my wing 2") == "MyWing2"
    assert class_name_for("2 wings") == "Discipline2Wings"
    assert class_name_for("") == "Discipline"
