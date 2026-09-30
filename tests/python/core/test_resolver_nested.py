from builders import assembly
from builders import component
from builders import driver
from builders import project

from gemseo_process_builder.core.drivers import driver_variables
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.resolver import PortRef
from gemseo_process_builder.core.resolver import level_view
from gemseo_process_builder.core.resolver import resolve


def doe_around_optimization(interface: dict[str, list[str]]) -> Project:
    """A DOE on ``a`` around an optimization of ``x`` minimizing ``f(x, a)``."""
    inner = driver(
        "Inner",
        "optimization",
        component("F", ins=["x", "a"], outs=["f", "g"]),
        config={
            "design_space": [{"variable": "x"}],
            "objectives": [{"variable": "f"}],
            "interface": interface,
        },
    )
    outer = driver("Outer", "doe", inner, config={"responses": ["f"]})
    return project(outer)


def test_parent_sees_only_the_interface() -> None:
    p = doe_around_optimization({"inputs": ["a"], "outputs": ["f", "x"]})
    resolution = resolve(p)
    assert resolution.scope_of["n-F"] == "n-Inner"
    assert resolution.derived["n-Inner"].inputs == {"a"}
    assert resolution.derived["n-Inner"].outputs == {"f", "x"}
    outer = resolution.couplings["n-Outer"]
    assert set(outer) == {"a", "f", "x"}
    assert resolution.free_inputs["n-Outer"] == ["a"]
    # g is not exposed: the parent does not see it.
    assert "g" not in outer


def test_ports_of_a_nested_driver_lead_to_its_components() -> None:
    p = doe_around_optimization({"inputs": ["a"], "outputs": ["f", "x"]})
    resolution = resolve(p)
    assert resolution.component_port(PortRef("n-Inner", "f", "out")) == PortRef(
        "n-F", "f", "out"
    )
    # A design variable is an input of the components inside.
    assert resolution.component_port(PortRef("n-Inner", "x", "out")) == PortRef(
        "n-F", "x", "in"
    )
    outer = p.find("n-Outer")
    assert isinstance(outer, DriverNode)
    variables = driver_variables(p, resolution, outer)
    assert sorted(variables.inputs) == ["a"]
    assert sorted(variables.outputs) == ["f", "x"]


def test_unknown_exposed_names_have_no_component_port() -> None:
    p = doe_around_optimization({"inputs": ["missing"], "outputs": ["f"]})
    resolution = resolve(p)
    assert resolution.component_port(PortRef("n-Inner", "missing", "in")) is None
    outer = p.find("n-Outer")
    assert isinstance(outer, DriverNode)
    assert driver_variables(p, resolve(p), outer).inputs == {}


def test_nothing_exposed_by_default() -> None:
    p = doe_around_optimization({})
    resolution = resolve(p)
    assert resolution.couplings.get("n-Outer", {}) == {}


def bilevel() -> Project:
    """Two sub-optimizations exchanging y_1 and y_2, and a system discipline."""
    sub1 = driver(
        "Sub1",
        "optimization",
        component("D1", ins=["x_1", "x_shared", "y_2"], outs=["y_1", "g_1"]),
        config={"design_space": [{"variable": "x_1"}]},
    )
    sub2 = driver(
        "Sub2",
        "optimization",
        component("D2", ins=["x_2", "x_shared", "y_1"], outs=["y_2", "g_2"]),
        config={"design_space": [{"variable": "x_2"}]},
    )
    system = driver(
        "System",
        "optimization",
        sub1,
        sub2,
        component("Obj", ins=["y_1", "y_2", "x_shared"], outs=["obj"]),
        config={"formulation": {"name": "BiLevel"}},
    )
    return project(system)


def test_bilevel_sub_scenarios_expose_what_bilevel_exchanges() -> None:
    resolution = resolve(bilevel())
    sub1 = resolution.derived["n-Sub1"]
    assert sub1.inputs == {"x_shared", "y_2"}
    assert sub1.outputs == {"y_1", "g_1", "x_1"}
    system = resolution.couplings["n-System"]
    assert [ref.node for ref in system["g_2"].producers] == ["n-Sub2"]
    assert resolution.free_inputs["n-System"] == ["x_shared"]
    assert resolution.issues == []


def test_bilevel_level_view_shows_the_exchanges() -> None:
    p = bilevel()
    edges = level_view(resolve(p), p, "n-System")["edges"]
    pairs = {(edge["source"], edge["target"]) for edge in edges}
    assert ("n-Sub1", "n-Sub2") in pairs
    assert ("n-Sub2", "n-Sub1") in pairs
    assert ("n-Sub1", "n-Obj") in pairs


def test_other_formulations_use_the_interface() -> None:
    p = bilevel()
    system = p.find("n-System")
    assert isinstance(system, DriverNode)
    system.config = {"formulation": {"name": "MDF"}}
    resolution = resolve(p)
    assert resolution.derived["n-Sub1"].outputs == set()


def test_nested_mda_driver_is_seen_like_an_assembly() -> None:
    mda = driver(
        "Loop",
        "mda",
        component("A", ins=["x", "b"], outs=["a"]),
        component("B", ins=["a"], outs=["b"]),
    )
    p = project(
        driver("Opt", "optimization", mda, component("C", ins=["a"], outs=["f"]))
    )
    resolution = resolve(p)
    assert resolution.derived["n-Loop"].inputs == {"x"}
    assert resolution.free_inputs["n-Opt"] == ["x"]
    assert [ref.node for ref in resolution.couplings["n-Opt"]["a"].producers] == [
        "n-Loop"
    ]


def test_deeply_nested_drivers_lead_to_components() -> None:
    inner = driver(
        "Inner",
        "optimization",
        component("F", ins=["x", "a"], outs=["f"]),
        config={"interface": {"inputs": ["a"], "outputs": ["f"]}},
    )
    middle = driver(
        "Middle",
        "doe",
        assembly("Group", inner),
        config={"interface": {"inputs": [], "outputs": ["f"]}},
    )
    p = project(driver("Outer", "doe", middle))
    resolution = resolve(p)
    assert resolution.component_port(PortRef("n-Middle", "f", "out")) == PortRef(
        "n-F", "f", "out"
    )
