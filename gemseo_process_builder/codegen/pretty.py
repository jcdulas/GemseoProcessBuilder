"""Expressions rendered the way ``ruff format`` (black style) lays them out.

Generated scripts must look hand-written and pass ``ruff format --check``
without running a formatter (SPEC § 10.2). Calls, lists and dictionaries are
therefore rendered with black's rules:

1. on one line if it fits in 88 columns;
2. otherwise with the brackets' content on one indented line, if it fits;
3. otherwise one element per indented line, with a trailing comma.

A string too long for its line is cut into pieces written one under the other
in parentheses (implicit concatenation), as a developer would.
"""

import re
from dataclasses import dataclass
from dataclasses import field

LINE_LENGTH = 88
INDENT = "    "


@dataclass
class Raw:
    """Code written as is (a name, a number, an attribute access…)."""

    text: str


@dataclass
class Call:
    """A call ``function(arguments)``; arguments are ``(keyword or "", expr)``."""

    function: str
    arguments: list[tuple[str, "Expr"]] = field(default_factory=list)


@dataclass
class ListExpr:
    """A list literal."""

    items: list["Expr"]


@dataclass
class DictExpr:
    """A dictionary literal with expression keys."""

    items: list[tuple["Expr", "Expr"]]


@dataclass
class Text:
    """A string value, cut into pieces when too long for its line."""

    value: str


Expr = Raw | Text | Call | ListExpr | DictExpr

_CUTS = re.compile(r"(?<=[ ,+/-])|(?<=[^*]\*)(?!\*)")
"""Where a long string is cut: after a space, a comma or an operator."""


def string(text: str) -> Raw:
    """A double-quoted string literal."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return Raw(f'"{escaped}"')


def _pieces(text: str, width: int) -> list[str]:
    """The literals of a string cut into pieces of at most ``width`` columns."""
    pieces: list[str] = []
    current = ""
    for part in (part for part in _CUTS.split(text) if part):
        if current and len(string(current + part).text) > width:
            pieces.append(current)
            current = ""
        current += part
    return [string(piece).text for piece in [*pieces, current]]


def _elements(expr: Expr) -> tuple[str, str, list[str]]:
    """Opening bracket, closing bracket and flat elements of a bracketed expr."""
    if isinstance(expr, Call):
        elements = [
            f"{keyword}={flat(value)}" if keyword else flat(value)
            for keyword, value in expr.arguments
        ]
        return f"{expr.function}(", ")", elements
    if isinstance(expr, ListExpr):
        return "[", "]", [flat(item) for item in expr.items]
    if isinstance(expr, DictExpr):
        return "{", "}", [f"{flat(key)}: {flat(value)}" for key, value in expr.items]
    msg = "Raw expressions have no elements."
    raise TypeError(msg)


def flat(expr: Expr) -> str:
    """The expression on one line."""
    if isinstance(expr, Raw):
        return expr.text
    if isinstance(expr, Text):
        return string(expr.value).text
    opening, closing, elements = _elements(expr)
    return opening + ", ".join(elements) + closing


def _parts(expr: Expr) -> list[tuple[str, Expr]]:
    """The elements of a bracketed expression, as (prefix, value) pairs."""
    if isinstance(expr, Call):
        return [
            (f"{keyword}=" if keyword else "", value)
            for keyword, value in expr.arguments
        ]
    if isinstance(expr, ListExpr):
        return [("", item) for item in expr.items]
    if isinstance(expr, DictExpr):
        return [(f"{flat(key)}: ", value) for key, value in expr.items]
    return []


def render(
    expr: Expr, prefix: str = "", suffix: str = "", indent: str = ""
) -> list[str]:
    """Lines of ``indent + prefix + expr + suffix``, formatted as ruff would."""
    one_line = f"{indent}{prefix}{flat(expr)}{suffix}"
    if len(one_line) <= LINE_LENGTH or isinstance(expr, Raw):
        return [one_line]
    if isinstance(expr, Text):
        inner = indent + INDENT
        # In parentheses, alone on its line when it fits there, like ruff.
        pieces = _pieces(expr.value, LINE_LENGTH - len(inner))
        return [
            f"{indent}{prefix}(",
            *(inner + piece for piece in pieces),
            f"{indent}){suffix}",
        ]
    opening, closing, elements = _elements(expr)
    if not elements:
        return [one_line]
    inner = indent + INDENT
    body = inner + ", ".join(elements)
    if len(body) <= LINE_LENGTH:
        return [f"{indent}{prefix}{opening}", body, f"{indent}{closing}{suffix}"]
    lines = [f"{indent}{prefix}{opening}"]
    for part_prefix, value in _parts(expr):
        lines.extend(render(value, part_prefix, ",", inner))
    lines.append(f"{indent}{closing}{suffix}")
    return lines


def statement(target: str, expr: Expr, indent: str = INDENT) -> list[str]:
    """Lines of ``target = expr`` (or of ``expr`` alone when target is empty)."""
    return render(expr, f"{target} = " if target else "", "", indent)


def returning(expr: Expr, indent: str = INDENT) -> list[str]:
    """Lines of ``return expr``."""
    return render(expr, "return ", "", indent)
