import time

from builders import assembly
from builders import component
from builders import driver
from builders import project

from gemseo_process_builder.core.graph import feedback_edges
from gemseo_process_builder.core.graph import strongly_connected_components
from gemseo_process_builder.core.model import Link
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.resolver import level_view
from gemseo_process_builder.core.resolver import resolve


def link(source: str, output: str, target: str, input_: str, link_id: str) -> Link:
    return Link(
        id=link_id,
        source={"node": source, "port": output},
        target={"node": target, "port": input_},
    )


def sellar() -> Project:
    return project(
        driver(
            "Opt",
            "optimization",
            component("S1", ins=["x_local", "x_shared", "y_2"], outs=["y_1"]),
            component("S2", ins=["x_shared", "y_1"], outs=["y_2"]),
            component("Sys", ins=["x_local", "x_shared", "y_1", "y_2"], outs=["obj"]),
        )
    )


def codes(p: Project) -> list[str]:
    return [issue.code for issue in resolve(p).issues]


def test_sellar_couplings_and_free_inputs() -> None:
    resolution = resolve(sellar())
    couplings = resolution.couplings["n-Opt"]
    assert [ref.node for ref in couplings["y_1"].producers] == ["n-S1"]
    assert sorted(c.node for c, kind in couplings["y_1"].consumers) == ["n-S2", "n-Sys"]
    assert resolution.free_inputs["n-Opt"] == ["x_local", "x_shared"]
    assert resolution.issues == []


def test_sellar_loop_and_feedback() -> None:
    view = level_view(resolve(sellar()), sellar(), "n-Opt")
    edges = {(e["source"], e["target"]): e for e in view["edges"]}
    assert set(edges) == {
        ("n-S1", "n-S2"),
        ("n-S2", "n-S1"),
        ("n-S1", "n-Sys"),
        ("n-S2", "n-Sys"),
    }
    assert edges["n-S2", "n-S1"]["feedback"]
    assert not edges["n-S1", "n-S2"]["feedback"]
    variable = edges["n-S1", "n-S2"]["variables"][0]
    assert variable == {
        "name": "y_1",
        "source_port": "y_1",
        "target_port": "y_1",
        "explicit": False,
    }


def test_explicit_link_renames_the_input() -> None:
    p = project(component("A", outs=["lift"]), component("B", ins=["load"]))
    p.links.append(link("n-A", "lift", "n-B", "load", "l-1"))
    resolution = resolve(p)
    assert resolution.global_name("n-B", "load", "in") == "lift"
    target = next(ref for ref in resolution.ports if ref.node == "n-B")
    assert resolution.ports[target].source == "link"
    edge = level_view(resolution, p, "n-root")["edges"][0]
    assert edge["variables"][0]["explicit"]
    p.links.clear()
    assert resolve(p).global_name("n-B", "load", "in") == "load"


def test_duplicate_producers() -> None:
    p = project(component("A", outs=["y"]), component("B", outs=["y"]))
    assert codes(p) == ["duplicate_producer"]


def test_multiple_links_to_one_input() -> None:
    p = project(
        component("A", outs=["a"]),
        component("B", outs=["b"]),
        component("C", ins=["x"]),
    )
    p.links.extend(
        [link("n-A", "a", "n-C", "x", "l-1"), link("n-B", "b", "n-C", "x", "l-2")]
    )
    resolution = resolve(p)
    assert [issue.code for issue in resolution.issues] == ["multiple_explicit_links"]
    assert resolution.global_name("n-C", "x", "in") == "a"


def test_link_to_missing_port() -> None:
    p = project(component("A", outs=["a"]), component("B", ins=["x"]))
    p.links.append(link("n-A", "nope", "n-B", "x", "l-1"))
    assert "link_to_missing_port" in codes(p)


def test_isolated_instances_do_not_conflict() -> None:
    p = project(
        component("Wing1", ins=["span"], outs=["lift"], isolated=True),
        component("Wing2", ins=["span"], outs=["lift"], isolated=True),
        component("Total", ins=["w1", "w2"], outs=["total"]),
    )
    p.links.extend(
        [
            link("n-Wing1", "lift", "n-Total", "w1", "l-1"),
            link("n-Wing2", "lift", "n-Total", "w2", "l-2"),
        ]
    )
    resolution = resolve(p)
    assert resolution.issues == []
    assert resolution.global_name("n-Wing1", "lift", "out") == "Wing1:lift"
    assert resolution.global_name("n-Total", "w2", "in") == "Wing2:lift"


def test_isolated_assembly_prefixes_its_content() -> None:
    p = project(assembly("Left", component("W", outs=["lift"]), isolated=True))
    assert resolve(p).global_name("n-W", "lift", "out") == "Left:lift"


def test_override_wins() -> None:
    p = project(component("A", outs=["y"]))
    p.root.children[0].ports[0].global_name = "renamed"  # type: ignore[union-attr]
    assert resolve(p).global_name("n-A", "y", "out") == "renamed"


def test_derived_ports_of_nested_assemblies() -> None:
    p = project(
        assembly(
            "G",
            component("A", ins=["x"], outs=["y"]),
            assembly("H", component("B", ins=["y", "z"], outs=["w"])),
        ),
        component("C", ins=["w"], outs=["out"]),
    )
    resolution = resolve(p)
    assert resolution.derived["n-H"].inputs == {"y", "z"}
    assert resolution.derived["n-G"].inputs == {"x", "z"}
    assert resolution.derived["n-G"].outputs == {"y", "w"}
    view = level_view(resolution, p, "n-root")
    assert view["ports"]["n-G"] == {"in": ["x", "z"], "out": ["w", "y"]}
    assert [(e["source"], e["target"]) for e in view["edges"]] == [("n-G", "n-C")]


def test_nested_driver_exposes_only_listed_variables() -> None:
    inner = driver("Inner", "optimization", component("A", ins=["x"], outs=["y"]))
    inner.config = {"exposed": {"inputs": [], "outputs": ["y"]}}
    p = project(inner, component("B", ins=["y"]))
    resolution = resolve(p)
    assert resolution.scope_of["n-A"] == "n-Inner"
    assert resolution.derived["n-Inner"].inputs == set()
    edges = level_view(resolution, p, "n-root")["edges"]
    assert [(edge["source"], edge["target"]) for edge in edges] == [("n-Inner", "n-B")]


def test_mode_checks() -> None:
    loop = assembly(
        "G",
        component("A", ins=["b"], outs=["a"]),
        component("B", ins=["a"], outs=["b"]),
        mode="chain",
    )
    assert codes(project(loop)) == ["loop_in_chain"]
    loop.mode = "parallel"
    assert codes(project(loop)) == ["dependency_in_parallel"]
    loop.mode = "auto"
    assert codes(project(loop)) == []


def test_strongly_connected_components() -> None:
    edges = {"a": ["b"], "b": ["c", "a"], "c": ["d"], "d": []}
    assert strongly_connected_components(["a", "b", "c", "d"], edges) == [
        ["d"],
        ["c"],
        ["a", "b"],
    ]


def test_feedback_edges_follow_display_order() -> None:
    edges = {"a": ["b"], "b": ["c"], "c": ["a"]}
    assert feedback_edges(["a", "b", "c"], edges) == {("c", "a")}
    assert feedback_edges(["c", "b", "a"], edges) == {("a", "b"), ("b", "c")}


def test_resolution_of_a_300_component_model_is_fast() -> None:
    components = []
    for index in range(300):
        components.append(
            component(
                f"C{index}",
                ins=[f"v{index - 1}", f"v{(index + 7) % 300}", "shared"],
                outs=[f"v{index}", f"extra{index}"],
            )
        )
    groups = [assembly(f"G{g}", *components[g * 30 : (g + 1) * 30]) for g in range(10)]
    p = project(*groups)
    start = time.perf_counter()
    resolution = resolve(p)
    assert time.perf_counter() - start < 0.3
    assert len(resolution.edges["n-root"]) > 0
