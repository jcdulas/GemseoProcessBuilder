"""One triggering and one clean case per nested driver rule."""

from typing import Any

from builders import component
from builders import driver
from builders import project

from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.resolver import resolve
from gemseo_process_builder.core.validation import ValidationContext
from gemseo_process_builder.core.validation import validate


def codes(p: Project) -> list[str]:
    context = ValidationContext(p, resolve(p), options={"show_unused_outputs": False})
    return [problem.code for problem in validate(context)]


def with_defaults(*ports: tuple[str, str]) -> list[Port]:
    return [
        Port(
            local_name=name,
            direction=direction,  # type: ignore[arg-type]
            default=1.0 if direction == "in" else None,
        )
        for name, direction in ports
    ]


def doe_around_optimization(interface: dict[str, Any]) -> Project:
    model = component("F")
    model.ports = with_defaults(("x", "in"), ("a", "in"), ("f", "out"))
    inner = driver(
        "Inner",
        "optimization",
        model,
        config={
            "design_space": [{"variable": "x", "lower": [0.0], "upper": [1.0]}],
            "objectives": [{"variable": "f"}],
            "interface": interface,
        },
    )
    outer = driver(
        "Outer",
        "doe",
        inner,
        config={
            "design_space": [{"variable": "a", "lower": [0.0], "upper": [1.0]}],
            "responses": ["f"],
        },
    )
    return project(outer)


def test_clean_nested_driver() -> None:
    assert (
        codes(doe_around_optimization({"inputs": ["a"], "outputs": ["f", "x"]})) == []
    )


def test_nested_driver_without_outputs() -> None:
    found = codes(doe_around_optimization({"inputs": ["a"]}))
    assert "nested_without_outputs" in found


def test_exposed_input_must_be_free() -> None:
    found = codes(doe_around_optimization({"inputs": ["a", "f"], "outputs": ["f"]}))
    assert found.count("exposed_input_not_free") == 1


def test_exposed_output_must_be_computed() -> None:
    found = codes(doe_around_optimization({"inputs": ["a"], "outputs": ["f", "g"]}))
    assert found.count("exposed_output_unknown") == 1


def test_drivers_of_the_model_need_no_interface() -> None:
    p = doe_around_optimization({})
    outer = p.root.children[0]
    p.root.children = list(outer.children)  # type: ignore[union-attr]
    assert "nested_without_outputs" not in codes(p)


def bilevel(system_variables: list[str]) -> Project:
    local = component("D1")
    local.ports = with_defaults(("x_1", "in"), ("x_shared", "in"), ("y_1", "out"))
    sub = driver(
        "Sub1",
        "optimization",
        local,
        config={
            "design_space": [{"variable": "x_1"}],
            "objectives": [{"variable": "y_1"}],
        },
    )
    system_model = component("Obj")
    system_model.ports = with_defaults(
        ("y_1", "in"), ("x_shared", "in"), ("obj", "out")
    )
    system = driver(
        "System",
        "optimization",
        sub,
        system_model,
        config={
            "formulation": {"name": "BiLevel"},
            "design_space": [{"variable": name} for name in system_variables],
            "objectives": [{"variable": "obj"}],
        },
    )
    return project(system)


def test_clean_bilevel() -> None:
    assert codes(bilevel(["x_shared"])) == []


def test_bilevel_without_sub_scenarios() -> None:
    p = bilevel(["x_shared"])
    system = p.root.children[0]
    system.children = system.children[1:]  # type: ignore[union-attr]
    assert "bilevel_without_sub_scenarios" in codes(p)


def test_bilevel_shared_design_variables() -> None:
    found = codes(bilevel(["x_shared", "x_1"]))
    assert "bilevel_shared_design_variable" in found
