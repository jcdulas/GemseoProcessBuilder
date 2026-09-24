import pytest
from builders import component
from builders import driver
from builders import project

from gemseo_process_builder.core.commands import CommandError
from gemseo_process_builder.core.commands import SetDriverConfig
from gemseo_process_builder.core.document import Document
from gemseo_process_builder.core.drivers import DriverConfig
from gemseo_process_builder.core.drivers import algorithm_name
from gemseo_process_builder.core.drivers import driver_config
from gemseo_process_builder.core.drivers import driver_variables
from gemseo_process_builder.core.drivers import formulation_name
from gemseo_process_builder.core.drivers import response_names
from gemseo_process_builder.core.drivers import variable_roles
from gemseo_process_builder.core.drivers import with_role
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.resolver import resolve


def sellar_like(kind: str = "optimization") -> Project:
    """Two coupled components in a driver; x and z are free inputs."""
    first = component("First", ["x", "z", "y2"], ["y1"])
    second = component("Second", ["z", "y1"], ["y2", "obj", "cstr"])
    first.ports[1] = Port(local_name="z", direction="in", shape=[2], default=[1, 2])
    return project(driver("Optimizer", kind, first, second))


def optimizer(p: Project) -> DriverNode:
    node = p.find("n-Optimizer")
    assert isinstance(node, DriverNode)
    return node


def test_set_driver_config_and_undo() -> None:
    p = sellar_like()
    document = Document(p)
    design_space = [{"variable": "x", "lower": [0.0], "upper": [1.0]}]
    document.execute(
        SetDriverConfig(id="n-Optimizer", field="design_space", value=design_space)
    )
    assert optimizer(p).config == {"design_space": design_space}
    assert document.undo_state()["undoLabel"] == "Change design variables"
    document.undo()
    assert optimizer(p).config == {}
    document.redo()
    assert driver_config(optimizer(p)).design_space[0].upper == [1.0]


def test_default_values_are_not_stored() -> None:
    p = sellar_like()
    Document(p).execute(
        SetDriverConfig(id="n-Optimizer", field="execution", value={"n_processes": 1})
    )
    assert optimizer(p).config == {}


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("design_space", [{"variable": "z", "size": 2, "lower": [0.0]}], "1 values"),
        ("objectives", [{"variable": "obj", "sense": "up"}], "sense"),
        ("nothing", 1, "no setting nothing"),
    ],
)
def test_invalid_config_is_refused(field: str, value: object, message: str) -> None:
    p = sellar_like()
    with pytest.raises(CommandError, match=message):
        Document(p).execute(SetDriverConfig(id="n-Optimizer", field=field, value=value))
    assert optimizer(p).config == {}


def test_only_drivers_have_a_config() -> None:
    with pytest.raises(CommandError, match="not a driver"):
        Document(sellar_like()).execute(
            SetDriverConfig(id="n-First", field="objectives", value=[])
        )


def test_defaults_by_kind() -> None:
    node = optimizer(sellar_like())
    config = DriverConfig()
    assert (algorithm_name(node, config), formulation_name(node, config)) == (
        "SLSQP",
        "MDF",
    )
    node.kind = "doe"
    assert (algorithm_name(node, config), formulation_name(node, config)) == (
        "LHS",
        "DisciplinaryOpt",
    )


def test_driver_variables_are_free_inputs_and_outputs() -> None:
    p = sellar_like()
    variables = driver_variables(p, resolve(p), optimizer(p))
    assert sorted(variables.inputs) == ["x", "z"]
    assert sorted(variables.outputs) == ["cstr", "obj", "y1", "y2"]


def test_with_role_builds_entries_from_the_port() -> None:
    p = sellar_like()
    first = p.find("n-First")
    z = first.port("z", "in")  # type: ignore[union-attr]
    assert z is not None
    field, value = with_role(DriverConfig(), "design_variable", "z", z)  # type: ignore[misc]
    assert field == "design_space"
    assert value[0]["size"] == 2
    assert value[0]["value"] == [1.0, 2.0]
    config = DriverConfig.model_validate({"design_space": value})
    assert with_role(config, "design_variable", "z", z) is None
    field, value = with_role(config, "response", "obj", z)  # type: ignore[misc]
    assert (field, value) == ("responses", ["obj"])


def test_roles_and_responses() -> None:
    node = optimizer(sellar_like())
    config = DriverConfig.model_validate(
        {
            "design_space": [{"variable": "x"}],
            "objectives": [{"variable": "obj"}],
            "constraints": [{"variable": "cstr"}],
            "observables": ["y1"],
        }
    )
    assert variable_roles(node, config) == {
        "x": ["design variable"],
        "obj": ["objective"],
        "cstr": ["constraint"],
        "y1": ["observable"],
    }
    assert response_names(node, config) == ["obj", "cstr", "y1"]
