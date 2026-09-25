from pathlib import Path

import pytest

from gemseo_process_builder.runtime.parsing import ParseError
from gemseo_process_builder.runtime.parsing import parse_number
from gemseo_process_builder.runtime.parsing import read_output
from gemseo_process_builder.runtime.spec import FileRule
from gemseo_process_builder.runtime.spec import KeyValueRule
from gemseo_process_builder.runtime.spec import MarkerRule
from gemseo_process_builder.runtime.spec import RegexRule
from gemseo_process_builder.runtime.spec import TableRule

OUTPUT = """Solver 1.0
iteration 1 residual 1.0e-2
iteration 2 residual 3.5e-5
MASS SUMMARY
  total   12.5   kg
  wing     4.25  kg
lift = 1.25D+03
STRESSES
  1  100.0
  2  150.5
  3  90.25

END
"""

HERE = Path()


def test_numbers() -> None:
    assert parse_number(" 1.5D+03 ") == 1500.0
    assert parse_number("-2e-3") == -0.002
    with pytest.raises(ParseError, match="'abc' is not a number"):
        parse_number("abc")


def test_regex_first_last_and_all() -> None:
    pattern = r"residual (\S+)"
    rule = RegexRule(variable="r", pattern=pattern)
    assert read_output(rule, OUTPUT, HERE) == 0.01
    rule = RegexRule(variable="r", pattern=pattern, occurrence="last")
    assert read_output(rule, OUTPUT, HERE) == 3.5e-5
    rule = RegexRule(variable="r", pattern=pattern, occurrence="all")
    assert read_output(rule, OUTPUT, HERE) == [0.01, 3.5e-5]


def test_marker_line_and_column() -> None:
    rule = MarkerRule(variable="mass", marker="MASS SUMMARY", line=2, column=1)
    assert read_output(rule, OUTPUT, HERE) == 4.25


def test_key_value() -> None:
    assert (
        read_output(KeyValueRule(variable="lift", key="lift"), OUTPUT, HERE) == 1250.0
    )


def test_table_until_an_empty_line() -> None:
    rule = TableRule(variable="stress", marker="STRESSES", column=1)
    assert read_output(rule, OUTPUT, HERE) == [100.0, 150.5, 90.25]


def test_file_rule(tmp_path: Path) -> None:
    (tmp_path / "field.vtk").write_text("data")
    rule = FileRule(variable="field", file="field.vtk")
    assert read_output(rule, "", tmp_path) == str(tmp_path / "field.vtk")
    with pytest.raises(ParseError, match="was not produced"):
        read_output(FileRule(variable="other", file="other.vtk"), "", tmp_path)


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        (MarkerRule(variable="m", marker="NOPE"), "marker 'NOPE' is not found"),
        (MarkerRule(variable="m", marker="MASS", line=1, column=7), "has no column 7"),
        (KeyValueRule(variable="drag", key="drag"), "no line drag = value"),
        (RegexRule(variable="r", pattern=r"cost (\S+)"), "matches nothing"),
        (RegexRule(variable="r", pattern=r"Solver (\S+)"), "'v1' is not a number"),
        (TableRule(variable="t", marker="END"), "is empty"),
    ],
)
def test_errors_name_the_rule(rule: object, message: str) -> None:
    with pytest.raises(ParseError, match=message) as error:
        read_output(rule, OUTPUT.replace("Solver 1.0", "Solver v1"), HERE)  # type: ignore[arg-type]
    assert "rule of" in str(error.value)
