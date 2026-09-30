from builders import component
from builders import driver
from builders import project

from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.resolver import resolve
from gemseo_process_builder.core.workflow_io import workflow_io


def sequence() -> Project:
    """Material, then an optimizer of a beam, then its cost."""
    optimizer = driver(
        "Opt",
        "optimization",
        component("Stress", ins=["width", "allowable", "load"], outs=["margin"]),
        component("Mass", ins=["width"], outs=["mass"]),
        config={
            "design_space": [{"variable": "width"}],
            "objectives": [{"variable": "mass"}],
            "constraints": [{"variable": "margin"}],
            "interface": {"inputs": ["allowable"], "outputs": ["mass"]},
        },
    )
    return project(
        component("Material", ins=["yield_stress"], outs=["allowable"]),
        optimizer,
        component("Cost", ins=["mass"], outs=["cost"]),
    )


def names(items: list[dict]) -> list[str]:
    return [item["name"] for item in items]


def test_the_start_has_the_values_to_give_and_the_end_the_final_results() -> None:
    p = sequence()
    io = workflow_io(resolve(p), p.root)
    # Not the design variable (set by the optimizer), nor a computed variable.
    assert names(io["inputs"]) == ["load", "yield_stress"]
    assert io["inputs"][0]["nodes"] == ["n-Stress"]
    # The margin only goes to the optimizer: a final result, like the cost.
    assert names(io["outputs"]) == ["cost", "margin"]
    assert names(io["others"]) == ["allowable", "mass"]


def test_outputs_chosen_by_the_user_are_at_the_end_too() -> None:
    p = sequence()
    p.root.exposed_outputs = ["mass"]
    io = workflow_io(resolve(p), p.root)
    assert names(io["outputs"]) == ["cost", "margin", "mass"]
    mass = io["outputs"][2]
    assert (mass["final"], mass["nodes"]) == (False, ["n-Mass"])


def test_a_level_inside_the_model_has_its_own_start_and_end() -> None:
    p = sequence()
    optimizer = p.find("n-Opt")
    assert optimizer is not None
    io = workflow_io(resolve(p), optimizer)  # type: ignore[arg-type]
    assert names(io["inputs"]) == ["allowable", "load"]
    assert names(io["outputs"]) == ["margin", "mass"]
