import io
from typing import Any

import numpy as np
import pytest
from builders import component
from builders import driver
from builders import project

from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.workers.derivatives_methods import _compare
from gemseo_process_builder.workers.derivatives_methods import check
from gemseo_process_builder.workers.derivatives_methods import origin
from gemseo_process_builder.workers.derivatives_methods import origins
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


def analytic(name: str, expressions: dict[str, str], inputs: list[str]) -> Any:
    node = component(name, kind="analytic", config={"expressions": expressions})
    node.ports = [
        Port(local_name=n, direction="in", default=1.0, default_text="1")
        for n in inputs
    ] + [Port(local_name=n, direction="out") for n in expressions]
    return node


def optimizer_script() -> Any:
    """y = x², then f = y + 3x, optimized on x."""
    optimizer = driver(
        "Opt",
        "optimization",
        analytic("Square", {"y": "x**2"}, ["x"]),
        analytic("Sum", {"f": "y + 3*x"}, ["x", "y"]),
        config={
            "design_space": [
                {"variable": "x", "lower": [-2.0], "upper": [2.0], "value": [1.0]}
            ],
            "objectives": [{"variable": "f"}],
            "algorithm": {"name": "SLSQP"},
        },
    )
    return generate(project(optimizer), "n-Opt")


def test_where_the_derivatives_come_from() -> None:
    from gemseo.core.chains.chain import MDOChain
    from gemseo.disciplines.analytic import AnalyticDiscipline
    from gemseo.disciplines.auto_py import AutoPyDiscipline

    exact = AnalyticDiscipline({"y": "x**2"})
    assert origin(exact) == "exact"
    approximated = AnalyticDiscipline({"z": "2*x"})
    approximated.set_jacobian_approximation()
    assert origin(approximated) == "approximated"

    def double(x: float = 1.0) -> float:
        z = 2 * x
        return z

    # Without a Jacobian function, GEMSEO approximates it.
    assert origin(AutoPyDiscipline(double)) == "approximated"
    from gemseo.core.discipline import Discipline

    class NoJacobian(Discipline):
        def _run(self, input_data: Any) -> None:
            return None

    assert origin(NoJacobian()) == "missing"
    # A group is as good as its worst member.
    assert origin(MDOChain([exact])) == "exact"
    assert origin(MDOChain([exact, approximated])) == "approximated"


def test_origins_of_a_script_by_node() -> None:
    script = optimizer_script()
    assert origins(script.source, script.mapping) == {
        "n-Square": "exact",
        "n-Sum": "exact",
    }


def test_a_driver_is_checked_through_its_process() -> None:
    script = optimizer_script()
    result = check(script.source, script.mapping)
    assert (result["inputs"], result["outputs"]) == (["x"], ["f"])
    (pair,) = result["pairs"]
    # df/dx = 2x + 3 through the chain, at x = 1.
    assert pair["ok"]
    assert pair["size"] == pytest.approx(5.0, rel=1e-6)
    assert result["ok"]
    assert result["origin"] == "exact"


def test_a_component_is_checked_at_the_point_its_process_computes() -> None:
    script = optimizer_script()
    result = check(script.source, script.mapping, "Sum")
    assert result["discipline"] == "Sum"
    assert result["ok"]
    assert {pair["input"] for pair in result["pairs"]} == {"x", "y"}


def test_wrong_derivatives_are_found() -> None:
    from gemseo.core.discipline import Discipline

    class Wrong(Discipline):
        def __init__(self) -> None:
            super().__init__()
            self.io.input_grammar.update_from_names(["x"])
            self.io.output_grammar.update_from_names(["y"])
            self.default_input_data = {"x": np.array([1.0])}

        def _run(self, input_data: Any) -> dict[str, Any]:
            return {"y": 2 * input_data["x"]}

        def _compute_jacobian(
            self, input_names: Any = (), output_names: Any = ()
        ) -> None:
            self._init_jacobian(input_names, output_names)
            self.jac["y"]["x"] = np.array([[3.0]])  # Should be 2.

    (pair,) = _compare(Wrong(), ["x"], ["y"], {"x": np.array([1.0])})
    assert not pair["ok"]
    assert pair["error"] == pytest.approx(1 / 2, rel=1e-4)
