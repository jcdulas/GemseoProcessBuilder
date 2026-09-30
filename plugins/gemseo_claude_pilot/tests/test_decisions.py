import pytest
from pydantic import ValidationError

from gemseo_claude_pilot.decisions import ACTION_KINDS
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.decisions import NoAction
from gemseo_claude_pilot.decisions import decision_schema


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "none"},
        {"kind": "change_settings", "settings": {"ftol_rel": 1e-8}},
        {"kind": "change_design_space", "variables": [{"name": "x", "upper": 3}]},
        {"kind": "switch_algorithm", "algo_name": "COBYLA"},
        {"kind": "stop", "reason": "converged"},
        {"kind": "add_samples", "algo_name": "LHS", "n_samples": 20},
    ],
)
def test_valid_actions(action):
    decision = Decision.model_validate({"diagnosis": "d", "action": action})
    assert decision.action.kind == action["kind"]


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "restart"},
        {"kind": "change_settings", "settings": {}},
        {"kind": "change_design_space", "variables": []},
        {"kind": "stop", "reason": "bored"},
        {"kind": "add_samples", "algo_name": "LHS", "n_samples": 0},
        {"kind": "switch_algorithm", "algo_name": "COBYLA", "typo": 1},
    ],
)
def test_invalid_actions(action):
    with pytest.raises(ValidationError):
        Decision.model_validate({"diagnosis": "d", "action": action})


def test_defaults():
    decision = Decision(diagnosis="All is well.")
    assert decision.action == NoAction()
    assert decision.severity == "info"
    with pytest.raises(ValidationError):
        Decision(diagnosis="d", confidence=2)


def test_schema_lists_every_action():
    schema = decision_schema()
    assert schema["required"] == ["diagnosis"]
    kinds = {
        definition["properties"]["kind"]["const"]
        for definition in schema["$defs"].values()
        if "kind" in definition.get("properties", {})
    }
    # The transformations of a restart have kinds too.
    transforms = {"binarize", "smooth", "set_region", "connect", "blend"}
    assert kinds == set(ACTION_KINDS) | transforms
