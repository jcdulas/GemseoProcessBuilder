"""The budget of a piloted run (spec § 5.4).

A run makes at most so many calls and spends at most so many tokens, and,
with an API key, at most an estimated cost. Once spent, the pilot stops asking
Claude and the run goes on with its current settings.
"""

from dataclasses import dataclass

from gemseo_claude_pilot.backends.base import Usage


@dataclass(frozen=True)
class Budget:
    """What one run may spend on Claude."""

    max_calls: int = 30
    """Exchanges with Claude."""

    max_tokens: int = 1_000_000
    """Input and output tokens of all the exchanges."""

    max_cost_usd: float | None = None
    """The estimated cost, with an API key; no limit by default."""

    def spent(self, calls: int, usage: Usage) -> str:
        """Why no more call may be made, or nothing."""
        if calls >= self.max_calls:
            return f"the {self.max_calls} calls of the budget are made"
        if usage.tokens >= self.max_tokens:
            return f"the {self.max_tokens:,} tokens of the budget are spent"
        if self.max_cost_usd is not None and usage.cost_usd >= self.max_cost_usd:
            return f"the ${self.max_cost_usd:g} of the budget are spent"
        return ""
