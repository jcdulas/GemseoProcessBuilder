from gemseo_claude_pilot.decisions import ACTION_KINDS
from gemseo_claude_pilot.prompts import system_prompt
from gemseo_claude_pilot.tools import SUBMIT_DECISION


def test_system_prompt_names_every_action_and_the_decision_tool():
    prompt = system_prompt()
    assert f"`{SUBMIT_DECISION.name}`" in prompt
    for kind in ACTION_KINDS:
        assert f"`{kind}`" in prompt
