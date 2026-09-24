"""Python literals for values stored in the project."""

import math
from typing import Any

from gemseo_process_builder.codegen.pretty import DictExpr
from gemseo_process_builder.codegen.pretty import Expr
from gemseo_process_builder.codegen.pretty import ListExpr
from gemseo_process_builder.codegen.pretty import Raw
from gemseo_process_builder.codegen.pretty import string


def number(value: float | int, text: str | None = None) -> Raw:
    """A number, as the user typed it when known (``1e-6`` stays ``1e-6``)."""
    if text is not None:
        cleaned = text.strip().replace("E", "e")
        try:
            float(cleaned)
        except ValueError:
            pass
        else:
            return Raw(cleaned)
    if isinstance(value, float) and math.isinf(value):
        return Raw('float("inf")' if value > 0 else '-float("inf")')
    return Raw(repr(value))


def literal(value: Any, text: str | None = None) -> Expr:
    """The literal of a JSON value.

    Args:
        value: A number, string, boolean, ``None``, list or dictionary.
        text: The value as typed by the user, used for numbers.
    """
    if isinstance(value, bool) or value is None:
        return Raw(repr(value))
    if isinstance(value, int | float):
        return number(value, text)
    if isinstance(value, str):
        return string(value)
    if isinstance(value, list | tuple):
        return ListExpr([literal(item) for item in value])
    if isinstance(value, dict):
        return DictExpr(
            [(string(str(key)), literal(item)) for key, item in value.items()]
        )
    msg = f"Cannot write a literal for {type(value).__name__}."
    raise TypeError(msg)
