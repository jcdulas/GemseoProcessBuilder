r"""Input files written from templates (SPEC § 7.5); pure Python.

A marker ``{{x}}`` is replaced by the value of the input ``x``, ``{{x:.6e}}``
by the value in a Python format. A vector is written as its values joined by
a separator. ``\{{`` writes ``{{`` itself.
"""

import re
from collections.abc import Mapping
from typing import Any

MARKER = re.compile(r"(?<!\\)\{\{\s*([A-Za-z_][\w.:-]*?)\s*(?::([^{}]*))?\}\}")
"""``{{name}}`` or ``{{name:format}}``, unless preceded by a backslash."""

ESCAPED = "\\{{"


class TemplateError(ValueError):
    """A template that cannot be rendered."""


def markers(template: str) -> list[str]:
    """The names used by a template, in order, without repetitions."""
    return list(dict.fromkeys(match.group(1) for match in MARKER.finditer(template)))


def _values(value: Any) -> list[Any]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, list | tuple):
        return [item for sub in value for item in _values(sub)]
    return [value]


def format_value(value: Any, spec: str = "", separator: str = " ") -> str:
    """The text of a value: a number in a format, or a vector of them."""
    items = _values(value)
    try:
        texts = [format(item, spec) if spec else str(item) for item in items]
    except (TypeError, ValueError) as error:
        msg = f"The format {spec!r} does not apply to {items}: {error}"
        raise TemplateError(msg) from None
    return separator.join(texts)


def render(template: str, values: Mapping[str, Any], separator: str = " ") -> str:
    """The text of a template with its markers replaced by the values.

    Raises:
        TemplateError: When a marker names no value, or its format does not apply.
    """

    def replace(match: re.Match[str]) -> str:
        name, spec = match.group(1), match.group(2) or ""
        if name not in values:
            msg = f"The template uses {{{{{name}}}}}, which is not an input."
            raise TemplateError(msg)
        return format_value(values[name], spec.strip(), separator)

    return MARKER.sub(replace, template).replace(ESCAPED, "{{")
