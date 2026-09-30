from pathlib import Path

import pytest
from builders import component
from builders import project

from gemseo_process_builder.app.api_resolve import InputParams
from gemseo_process_builder.app.api_resolve import LevelParams
from gemseo_process_builder.app.api_resolve import ResolutionService
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.core.model import ComponentNode


@pytest.fixture
def service(tmp_path: Path) -> ResolutionService:
    session = ProjectSession(tmp_path / "untitled.gpb.json.autosave")
    # Two components using the length, one computing the mass from them.
    session.project = project(
        component("Beam", ["length", "width"], ["mass"]),
        component("Paint", ["length"], ["area"]),
        component("Cost", ["mass"], ["cost"]),
    )
    return ResolutionService(session, Bridge(MethodRegistry()))


def test_a_value_typed_at_the_start_goes_to_every_node_using_it(
    service: ResolutionService,
) -> None:
    io = service.workflow(LevelParams(level="n-root"))
    assert [item["name"] for item in io["inputs"]] == ["length", "width"]
    assert [item["name"] for item in io["outputs"]] == ["area", "cost"]
    service.set_input(InputParams(level="n-root", name="length", value=2.5, text="2.5"))
    project = service.session.project
    for name in ("n-Beam", "n-Paint"):
        node = project.find(name)
        assert isinstance(node, ComponentNode)
        port = node.port("length", "in")
        assert port is not None
        assert (port.default, port.default_text) == (2.5, "2.5")
    # One undo step gives the old values back everywhere.
    service.session.document.undo()
    beam = project.find("n-Beam")
    assert isinstance(beam, ComponentNode)
    assert beam.port("length", "in").default is None  # type: ignore[union-attr]


def test_only_inputs_of_the_workflow_can_be_set(service: ResolutionService) -> None:
    with pytest.raises(BridgeError):
        service.set_input(InputParams(level="n-root", name="mass", value=1, text="1"))
    with pytest.raises(BridgeError):
        service.workflow(LevelParams(level="n-Beam"))
