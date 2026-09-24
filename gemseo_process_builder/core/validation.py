"""Static validation of a project (SPEC § 9.1).

A rule is a function ``(context) -> list[Problem]`` registered with ``@rule``.
Rules run in the UI process after each change; they must stay fast.
"""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from typing import Literal

from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.resolver import Resolution

Level = Literal["error", "warning", "info"]
LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class Problem:
    """A message shown in the Problems panel."""

    code: str
    level: Level
    message: str
    node: str = ""
    port: str = ""
    link: str = ""
    quick_fixes: list[str] = field(default_factory=list)
    """Ids of the fixes offered, like ``isolate_namespace``."""

    @property
    def key(self) -> str:
        """A key that stays the same while the problem is not fixed."""
        return f"{self.code}:{self.node}:{self.port}:{self.link}"

    def to_dict(self) -> dict[str, object]:
        """The problem as sent to the page."""
        return {
            "key": self.key,
            "code": self.code,
            "level": self.level,
            "message": self.message,
            "node": self.node,
            "port": self.port,
            "link": self.link,
            "quick_fixes": self.quick_fixes,
        }


@dataclass
class ValidationContext:
    """What rules can look at."""

    project: Project
    resolution: Resolution
    component_errors: dict[str, str] = field(default_factory=dict)
    """Introspection errors by component id."""

    options: dict[str, bool] = field(default_factory=dict)
    """User options, like ``show_unused_outputs``."""

    algorithms: dict[str, dict[str, dict[str, bool]]] = field(default_factory=dict)
    """``{kind: {algorithm: capabilities}}``, for the kinds already listed."""


Rule = Callable[[ValidationContext], list[Problem]]

RULES: dict[str, Rule] = {}


def rule(name: str) -> Callable[[Rule], Rule]:
    """Register a validation rule under a name."""

    def register(function: Rule) -> Rule:
        RULES[name] = function
        return function

    return register


def validate(context: ValidationContext) -> list[Problem]:
    """Run every rule and return the problems, errors first."""
    # The rule modules register themselves when imported.
    from gemseo_process_builder.core.rules import drivers  # noqa: F401
    from gemseo_process_builder.core.rules import structure  # noqa: F401

    problems: list[Problem] = []
    seen: set[str] = set()
    for function in RULES.values():
        for problem in function(context):
            if problem.key not in seen:
                seen.add(problem.key)
                problems.append(problem)
    return sorted(problems, key=lambda problem: LEVEL_ORDER[problem.level])
