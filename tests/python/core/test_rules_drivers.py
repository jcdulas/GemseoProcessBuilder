"""One triggering and one clean case per driver rule."""

from typing import Any

import pytest
from builders import component
from builders import driver
from builders import project

from gemseo_process_builder.core.drivers import DriverConfig
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.resolver import resolve
from gemseo_process_builder.core.rules.drivers import incompatibilities
from gemseo_process_builder.core.validation import ValidationContext
from gemseo_process_builder.core.validation import validate

SLSQP = {
    "handle_equality_constraints": True,
    "handle_inequality_constraints": True,
    "handle_multiobjective": False,
    "handle_integer_variables": False,
}
NELDER_MEAD = {**SLSQP, "handle_inequality_constraints": False}

CLEAN: dict[str, Any] = {
    "design_space": [{"variable": "x", "lower": [0.0], "upper": [2.0], "value": [1.0]}],
    "objectives": [{"variable": "obj"}],
    "constraints": [{"variable": "cstr"}],
}


def study(kind: str = "optimization", **config: Any) -> Project:
    model = component("Model", ["x", "label"], ["obj", "cstr", "name"])
    model.ports[1] = Port(local_name="label", direction="in", dtype="str", default="a")
    model.ports[4] = Port(local_name="name", direction="out", dtype="str")
    model.ports[0] = Port(local_name="x", direction="in", default=1.0)
    return project(driver("Study", kind, model, config=config))


def driver_codes(p: Project, algorithms: dict[str, Any] | None = None) -> list[str]:
    context = ValidationContext(
        p,
        resolve(p),
        options={"show_unused_outputs": False},
        algorithms={"optimization": algorithms or {"SLSQP": SLSQP}},
    )
    return [
        problem.code
        for problem in validate(context)
        if problem.code != "free_input_without_default"
    ]


def test_clean_optimization() -> None:
    assert driver_codes(study(**CLEAN)) == []


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"design_space": [{"variable": "obj"}]}, "design_variable_not_free"),
        ({"design_space": [{"variable": "label"}]}, "text_design_variable"),
        (
            {"design_space": [{"variable": "x", "lower": [3.0], "upper": [2.0]}]},
            "inconsistent_bounds",
        ),
        (
            {"design_space": [{"variable": "x", "upper": [2.0], "value": [5.0]}]},
            "value_out_of_bounds",
        ),
        ({"objectives": []}, "missing_objective"),
        ({"objectives": [{"variable": "nothing"}]}, "not_an_output"),
        ({"observables": ["name"]}, "text_output"),
        ({"algorithm": {"name": "NOT_INSTALLED"}}, "unknown_algorithm"),
        (
            {"objectives": [{"variable": "obj"}, {"variable": "cstr"}]},
            "incompatible_algorithm",
        ),
    ],
)
def test_optimization_rules(changes: dict[str, Any], code: str) -> None:
    assert driver_codes(study(**{**CLEAN, **changes})) == [code]


def test_doe_needs_a_response() -> None:
    doe = {"design_space": CLEAN["design_space"]}
    assert driver_codes(study("doe", **doe)) == ["missing_response"]
    assert driver_codes(study("doe", **doe, responses=["obj"])) == []


def test_parametric_levels() -> None:
    levels = [{"variable": "x", "mode": "list", "values": []}]
    assert driver_codes(study("parametric", levels=levels, responses=["obj"])) == [
        "empty_levels"
    ]
    levels = [{"variable": "x", "lower": 2.0, "upper": 1.0}]
    assert driver_codes(study("parametric", levels=levels, responses=["obj"])) == [
        "inconsistent_bounds"
    ]


def test_unreadable_config() -> None:
    assert driver_codes(study(objectives="obj")) == ["invalid_driver_config"]


def test_algorithm_checks_wait_for_the_worker() -> None:
    p = study(**CLEAN, algorithm={"name": "NOT_INSTALLED"})
    context = ValidationContext(p, resolve(p), options={"show_unused_outputs": False})
    assert "unknown_algorithm" not in [problem.code for problem in validate(context)]


def test_incompatibility_reasons() -> None:
    config = DriverConfig.model_validate(
        {
            **CLEAN,
            "constraints": [{"variable": "cstr"}, {"variable": "obj", "type": "eq"}],
            "design_space": [{"variable": "x", "type": "integer"}],
        }
    )
    assert incompatibilities(config, NELDER_MEAD) == [
        "does not handle inequality constraints",
        "does not handle integer variables",
    ]
    assert incompatibilities(config, {**SLSQP, "handle_integer_variables": True}) == []


def test_outputs_used_by_a_driver_are_not_unused() -> None:
    p = study(**CLEAN)
    context = ValidationContext(p, resolve(p), options={"show_unused_outputs": True})
    unused = [p.port for p in validate(context) if p.code == "unused_output"]
    assert unused == ["name"]
