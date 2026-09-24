"""Decorators marking user functions as reusable components.

Example:
    >>> from gemseo_process_builder.runtime import component
    >>> @component(units={"lift": "N", "area": "m**2"}, description="Wing lift")
    ... def lift(area=10.0, speed=50.0):
    ...     lift = 0.6 * area * speed**2
    ...     return lift
"""

from collections.abc import Callable
from typing import Any
from typing import TypeVar

COMPONENT_ATTRIBUTE = "__gpb_component__"

F = TypeVar("F", bound=Callable[..., Any])


def component(
    *,
    units: dict[str, str] | None = None,
    description: str = "",
    icon: str = "",
) -> Callable[[F], F]:
    """Show a function in the component library of GEMSEO Process Builder.

    The function becomes a Python function component: its arguments are the
    inputs and the names it returns are the outputs, as for GEMSEO's
    ``AutoPyDiscipline``. The function itself is not changed.

    Args:
        units: Units of the inputs and outputs, by name (pint syntax).
        description: A short description shown in the library.
        icon: An optional icon name.
    """

    def mark(function: F) -> F:
        setattr(
            function,
            COMPONENT_ATTRIBUTE,
            {"units": dict(units or {}), "description": description, "icon": icon},
        )
        return function

    return mark
