"""A Claude copilot that watches GEMSEO optimizations and adjusts their strategy.

Specified in docs/CLAUDE_PILOT_SPEC.md of the GEMSEO Process Builder repository.
"""

from gemseo_claude_pilot.budget import Budget
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.guardrails import Checked
from gemseo_claude_pilot.guardrails import Limits
from gemseo_claude_pilot.guardrails import RejectedDecisionError
from gemseo_claude_pilot.guardrails import check
from gemseo_claude_pilot.pilot import ClaudePilot
from gemseo_claude_pilot.pilot import PilotMode
from gemseo_claude_pilot.pilot import PilotResult
from gemseo_claude_pilot.privacy import Anonymizer
from gemseo_claude_pilot.privacy import DataLevel

__version__ = "0.1.0"

__all__ = [
    "Anonymizer",
    "Budget",
    "Checked",
    "ClaudePilot",
    "DataLevel",
    "Decision",
    "Limits",
    "PilotMode",
    "PilotResult",
    "RejectedDecisionError",
    "check",
]
