"""Executable wrappers as components: their ports, and the script using them."""

import io
from pathlib import Path

import pytest
from golden_projects import example

from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.workers.codegen_methods import dry_run
from gemseo_process_builder.workers.component_methods import IntrospectionError
from gemseo_process_builder.workers.component_methods import introspect
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel

DESCRIPTOR = (
    Path(__file__).parents[3] / "examples" / "external_code" / "solver.gpbwrap.json"
)


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


def test_ports_come_from_the_descriptor() -> None:
    ports = introspect("executable", {"descriptor_path": str(DESCRIPTOR)})
    assert [(port["local_name"], port["direction"]) for port in ports] == [
        ("x", "in"),
        ("y", "in"),
        ("f", "out"),
        ("g", "out"),
    ]
    assert ports[0]["default"] == 0.0
    assert ports[2]["description"] == "Cost"


def test_missing_descriptor() -> None:
    with pytest.raises(IntrospectionError, match="Choose a wrapper descriptor"):
        introspect("executable", {})
    with pytest.raises(IntrospectionError, match="not a valid wrapper descriptor"):
        introspect(
            "executable",
            {"descriptor_path": str(DESCRIPTOR.parent / "no.gpbwrap.json")},
        )


def test_the_example_builds() -> None:
    script = generate(example("external_code/external_code"), "n-optimizer")
    assert "ExecutableDiscipline.from_descriptor(SOLVER_WRAPPER)" in script.source
    assert dry_run(script.source, script.mapping) == []
