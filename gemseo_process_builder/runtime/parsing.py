"""Output values read from the files of an external code (SPEC § 7.5); pure Python.

Each rule of ``spec.py`` reads one output. Errors name the rule, the file and
what was not found, so that the user can fix the wrapper.
"""

import re
from pathlib import Path

from gemseo_process_builder.runtime.spec import FileRule
from gemseo_process_builder.runtime.spec import KeyValueRule
from gemseo_process_builder.runtime.spec import MarkerRule
from gemseo_process_builder.runtime.spec import OutputRule
from gemseo_process_builder.runtime.spec import RegexRule
from gemseo_process_builder.runtime.spec import TableRule


class ParseError(ValueError):
    """An output that cannot be read."""


def parse_number(text: str, where: str = "") -> float:
    """A number, also in Fortran notation (``1.5D+03``).

    Raises:
        ParseError: When the text is not a number.
    """
    cleaned = text.strip().replace("D", "E").replace("d", "e")
    try:
        return float(cleaned)
    except ValueError:
        msg = f"{where}{text.strip()!r} is not a number."
        raise ParseError(msg) from None


def _describe(rule: OutputRule) -> str:
    return f"The {rule.kind} rule of {rule.variable} ({rule.file}): "


def _regex(rule: RegexRule, text: str) -> float | list[float]:
    where = _describe(rule)
    try:
        matches = list(re.finditer(rule.pattern, text, re.MULTILINE))
    except re.error as error:
        msg = f"{where}invalid pattern: {error}."
        raise ParseError(msg) from None
    if not matches:
        msg = f"{where}the pattern {rule.pattern!r} matches nothing."
        raise ParseError(msg)
    values = [parse_number(match.group(rule.group), where) for match in matches]
    if rule.occurrence == "all":
        return values
    return values[0] if rule.occurrence == "first" else values[-1]


def _marker_line(lines: list[str], marker: str, where: str) -> int:
    for index, line in enumerate(lines):
        if marker in line:
            return index
    msg = f"{where}the marker {marker!r} is not found."
    raise ParseError(msg)


def _column(line: str, column: int, where: str) -> str:
    columns = line.split()
    if column >= len(columns):
        msg = f"{where}the line {line.strip()!r} has no column {column}."
        raise ParseError(msg)
    return columns[column]


def _marker(rule: MarkerRule, text: str) -> float:
    where = _describe(rule)
    lines = text.splitlines()
    index = _marker_line(lines, rule.marker, where) + rule.line
    if index >= len(lines):
        msg = f"{where}there is no line {rule.line} after the marker."
        raise ParseError(msg)
    return parse_number(_column(lines[index], rule.column, where), where)


def _key_value(rule: KeyValueRule, text: str) -> float:
    where = _describe(rule)
    for line in text.splitlines():
        key, separator, value = line.partition(rule.separator)
        if separator and key.strip() == rule.key:
            return parse_number(value, where)
    msg = f"{where}no line {rule.key} {rule.separator} value."
    raise ParseError(msg)


def _table(rule: TableRule, text: str) -> list[float]:
    where = _describe(rule)
    lines = text.splitlines()
    start = _marker_line(lines, rule.marker, where) + 1 + rule.skip
    values = []
    for line in lines[start:]:
        if (rule.end and rule.end in line) or (not rule.end and not line.strip()):
            break
        values.append(parse_number(_column(line, rule.column, where), where))
    if not values:
        msg = f"{where}the table after {rule.marker!r} is empty."
        raise ParseError(msg)
    return values


def read_output(
    rule: OutputRule, text: str, workdir: Path
) -> float | list[float] | str:
    """The value of an output.

    Args:
        rule: How to read it.
        text: The content of the rule's file (unused by ``file`` rules).
        workdir: The working folder of the run.

    Raises:
        ParseError: When the value cannot be read.
    """
    if isinstance(rule, RegexRule):
        return _regex(rule, text)
    if isinstance(rule, MarkerRule):
        return _marker(rule, text)
    if isinstance(rule, KeyValueRule):
        return _key_value(rule, text)
    if isinstance(rule, TableRule):
        return _table(rule, text)
    if isinstance(rule, FileRule):
        path = workdir / rule.file
        if not path.is_file():
            msg = f"{_describe(rule)}the file was not produced."
            raise ParseError(msg)
        return str(path)
    msg = f"Unknown rule {rule!r}."  # pragma: no cover - the union is closed
    raise ParseError(msg)
