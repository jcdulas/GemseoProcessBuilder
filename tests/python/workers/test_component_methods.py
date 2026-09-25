import io
from pathlib import Path

import pytest

from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.ports import merge_ports
from gemseo_process_builder.workers.component_methods import IntrospectionError
from gemseo_process_builder.workers.component_methods import init_signature
from gemseo_process_builder.workers.component_methods import introspect
from gemseo_process_builder.workers.component_methods import reserved_names
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel

FIXTURES = Path(__file__).parents[1] / "catalog" / "fixtures"


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


def by_name(ports: list[dict]) -> dict[tuple[str, str], dict]:
    return {(port["local_name"], port["direction"]): port for port in ports}


def test_analytic_ports() -> None:
    ports = by_name(introspect("analytic", {"expressions": {"y": "x**2 + sin(z)"}}))
    assert set(ports) == {("x", "in"), ("z", "in"), ("y", "out")}
    assert ports["x", "in"]["shape"] == [1]
    assert ports["y", "out"]["shape"] == [1]


def test_analytic_syntax_error() -> None:
    with pytest.raises(IntrospectionError):
        introspect("analytic", {"expressions": {"y": "x**"}})


def test_analytic_reserved_names() -> None:
    with pytest.raises(IntrospectionError, match="S cannot be a variable name"):
        introspect("analytic", {"expressions": {"lift": "0.5*v**2*S"}})
    # SymPy functions and numbers used as variables, and keywords.
    assert reserved_names({"y": "gamma*E + test", "lambda": "1"}) == [
        "E",
        "gamma",
        "lambda",
        "test",
    ]
    # Functions called, pi, exponents of numbers and names containing them are fine.
    assert reserved_names({"y": "sin(x) + pi*1e5 + gamma_1 + Max(a, b)"}) == []


def test_analytic_without_expressions() -> None:
    with pytest.raises(IntrospectionError, match="at least one expression"):
        introspect("analytic", {"expressions": {}})


def test_python_function_ports_and_units() -> None:
    config = {"module_path": str(FIXTURES / "disciplines.py"), "function": "lift"}
    ports = by_name(introspect("python_function", config))
    assert set(ports) == {("area", "in"), ("lift", "out")}
    assert ports["area", "in"]["default"] == [10.0]
    assert ports["area", "in"]["unit"] == "m**2"
    assert ports["lift", "out"]["unit"] == "N"


def test_python_class_from_installed_module() -> None:
    config = {"module": "gemseo.problems.mdo.sellar.sellar_1", "class": "Sellar1"}
    ports = by_name(introspect("python_class", config))
    assert ports["x_shared", "in"]["shape"] == [2]
    assert ports["x_shared", "in"]["dtype"] == "float"
    assert ("y_1", "out") in ports


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"module": "gemseo.problems.mdo.sellar.sellar_1"}, "No class"),
        ({"module_path": "missing.py", "class": "A"}, "does not exist"),
        (
            {"module": "gemseo.problems.mdo.sellar.sellar_1", "class": "Nope"},
            "no class",
        ),
        ({"module": "no_such_module_xyz", "class": "A"}, "cannot be imported"),
    ],
)
def test_python_class_errors(config: dict, message: str) -> None:
    with pytest.raises(IntrospectionError, match=message):
        introspect("python_class", config)


def test_init_signature() -> None:
    config = {"module": "gemseo.problems.mdo.sellar.sellar_1", "class": "Sellar1"}
    parameters = {p["name"]: p for p in init_signature(config)}
    assert parameters["n"]["default"] == 1
    assert parameters["k"]["required"] is False


def test_merge_keeps_user_fields() -> None:
    old = [
        Port(local_name="x", direction="in", unit="m", description="span"),
        Port(local_name="gone", direction="in"),
        Port(local_name="linked", direction="out"),
    ]
    new = [
        {"local_name": "x", "direction": "in", "shape": [2]},
        {"local_name": "y", "direction": "out", "unit": "N"},
    ]
    ports = {p.local_name: p for p in merge_ports(old, new, {("linked", "out")})}
    assert set(ports) == {"x", "y", "linked"}
    assert (ports["x"].unit, ports["x"].description, ports["x"].shape) == (
        "m",
        "span",
        [2],
    )
    assert ports["y"].unit == "N"
    assert ports["linked"].missing


def test_merge_keeps_user_default() -> None:
    old = [Port(local_name="x", direction="in", default=3.0, default_text="3")]
    (port,) = merge_ports(old, [{"local_name": "x", "direction": "in"}], set())
    assert (port.default, port.default_text) == (3.0, "3")
