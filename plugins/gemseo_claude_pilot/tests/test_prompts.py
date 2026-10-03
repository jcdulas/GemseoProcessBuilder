from gemseo_claude_pilot.decisions import ACTION_KINDS
from gemseo_claude_pilot.prompts import system_prompt
from gemseo_claude_pilot.tools import SUBMIT_DECISION


def test_system_prompt_names_every_action_and_the_decision_tool():
    prompt = system_prompt()
    assert f"`{SUBMIT_DECISION.name}`" in prompt
    for kind in ACTION_KINDS:
        assert f"`{kind}`" in prompt


def test_the_small_gain_of_the_main_run_is_no_reason_not_to_relax():
    prompt = system_prompt()
    assert "is no reason not to" in prompt
    assert "a third of its budget or more is unspent" in prompt
    assert "`cycles` 3, `decay` 0.7" in prompt
    assert "can be many times the gain left" in prompt
