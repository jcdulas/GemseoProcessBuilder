from pathlib import Path
from typing import Any

import pytest
from builders import component
from builders import driver
from builders import project

from gemseo_process_builder.app.api_drivers import DriverAlgorithmsParams
from gemseo_process_builder.app.api_drivers import DriverParams
from gemseo_process_builder.app.api_drivers import DriverService
from gemseo_process_builder.app.api_drivers import RoleParams
from gemseo_process_builder.app.api_resolve import ResolutionService
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.core.model import Port


class FakeAlgorithms:
    """Two optimization algorithms, as the worker describes them."""

    def list_algorithms(self, params: Any) -> list[dict[str, Any]]:
        capabilities = {
            "handle_equality_constraints": True,
            "handle_inequality_constraints": True,
        }
        return [
            {"name": "SLSQP", "capabilities": capabilities},
            {
                "name": "NELDER-MEAD",
                "capabilities": {
                    **capabilities,
                    "handle_inequality_constraints": False,
                },
            },
        ]


@pytest.fixture
def service(tmp_path: Path) -> DriverService:
    session = ProjectSession(tmp_path / "untitled.gpb.json.autosave")
    model = component("Model", ["x", "z"], ["obj", "cstr"])
    model.ports[1] = Port(local_name="z", direction="in", shape=[2], default=[1, 2])
    session.project = project(driver("Optimizer", "optimization", model))
    bridge = Bridge(MethodRegistry())
    resolution = ResolutionService(session, bridge)
    return DriverService(session, bridge, resolution, FakeAlgorithms())  # type: ignore[arg-type]


def assign(service: DriverService, port: str, direction: str, role: str) -> Any:
    return service.assign_role(
        RoleParams(node="n-Model", port=port, direction=direction, role=role)  # type: ignore[arg-type]
    )


def test_variables_of_the_driver(service: DriverService) -> None:
    variables = service.variables(DriverParams(id="n-Optimizer"))
    assert [(v["name"], v["size"]) for v in variables["inputs"]] == [("x", 1), ("z", 2)]
    assert [v["name"] for v in variables["outputs"]] == ["cstr", "obj"]


def test_assign_roles_then_read_them_by_port(service: DriverService) -> None:
    assert assign(service, "z", "in", "design_variable") == {
        "driver": "n-Optimizer",
        "field": "design_space",
    }
    assign(service, "obj", "out", "objective")
    assign(service, "obj", "out", "objective")  # Already there: no change.
    assert service.session.project.find("n-Optimizer").config == {  # type: ignore[union-attr]
        "design_space": [{"variable": "z", "size": 2, "value": [1.0, 2.0]}],
        "objectives": [{"variable": "obj"}],
    }
    assert service.port_roles() == {
        "n-Model/in/z": ["design variable"],
        "n-Model/out/obj": ["objective"],
    }
    assert service.session.document.undo_state()["undoLabel"] == "Change objectives"


def test_impossible_roles_are_refused(service: DriverService) -> None:
    with pytest.raises(BridgeError, match="not possible"):
        assign(service, "obj", "out", "design_variable")
    with pytest.raises(BridgeError, match="not possible"):
        assign(service, "x", "in", "response")


def test_algorithms_with_the_reason_they_cannot_be_used(service: DriverService) -> None:
    assign(service, "cstr", "out", "constraint")
    algorithms = service.algorithms_for(
        DriverAlgorithmsParams(id="n-Optimizer", kind="optimization")
    )
    assert {item["name"]: item["reasons"] for item in algorithms} == {
        "SLSQP": [],
        "NELDER-MEAD": ["does not handle inequality constraints"],
    }
