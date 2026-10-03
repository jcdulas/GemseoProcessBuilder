"""The prompts sent to Claude, versioned: a change of wording is a new version."""

from importlib.resources import files

SYSTEM_PROMPT_VERSION = "21"


def system_prompt(version: str = SYSTEM_PROMPT_VERSION) -> str:
    """The system prompt of a version."""
    return files(__package__).joinpath(f"system_v{version}.md").read_text("utf-8")
