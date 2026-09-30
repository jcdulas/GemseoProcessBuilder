from builders import assembly
from builders import component
from builders import driver
from builders import project

from gemseo_process_builder.core.model import Endpoint
from gemseo_process_builder.core.model import Link
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.n2 import ORDER_KEY
from gemseo_process_builder.core.n2 import n2_matrix
from gemseo_process_builder.core.resolver import resolve


def sellar() -> Project:
    return project(
        driver(
            "Opt",
            "optimization",
            component("S1", ins=["x_1", "x_shared", "y_2"], outs=["y_1"]),
            component("S2", ins=["x_shared", "y_1"], outs=["y_2"]),
            component("Sys", ins=["x_1", "y_1", "y_2"], outs=["obj"]),
        )
    )


def matrix(p: Project, level: str) -> dict:
    return n2_matrix(p, resolve(p), level)


def cells(data: dict) -> dict[tuple[str, str], tuple[list[str], bool]]:
    ids = [entry["id"] for entry in data["entries"]]
    return {
        (ids[cell["row"]], ids[cell["col"]]): (cell["variables"], cell["feedback"])
        for cell in data["cells"]
    }


def test_sellar_couplings_and_feedback() -> None:
    data = matrix(sellar(), "n-Opt")
    assert [entry["name"] for entry in data["entries"]] == ["S1", "S2", "Sys"]
    assert cells(data) == {
        ("n-S1", "n-S2"): (["y_1"], False),
        ("n-S1", "n-Sys"): (["y_1"], False),
        ("n-S2", "n-S1"): (["y_2"], True),
        ("n-S2", "n-Sys"): (["y_2"], False),
    }


def test_cells_between_components_give_their_ports() -> None:
    p = sellar()
    p.links.append(
        Link(
            source=Endpoint(node="n-S2", port="y_2"),
            target=Endpoint(node="n-S1", port="y_2"),
        )
    )
    data = matrix(p, "n-Opt")
    feedback = next(cell for cell in data["cells"] if cell["feedback"])
    assert feedback["links"] == [
        {"name": "y_2", "source_port": "y_2", "target_port": "y_2", "explicit": True}
    ]
    forward = data["cells"][0]
    assert forward["links"][0]["explicit"] is False


def test_display_order_is_stored_in_the_layout() -> None:
    p = sellar()
    p.layout.extra[ORDER_KEY] = {"n-Opt": ["n-Sys", "n-S2"]}
    data = matrix(p, "n-Opt")
    # Children missing from the stored order come last.
    assert [entry["name"] for entry in data["entries"]] == ["Sys", "S2", "S1"]
    assert cells(data)[("n-S1", "n-S2")] == (["y_1"], True)


def test_chain_assemblies_keep_their_execution_order() -> None:
    chain = assembly(
        "Chain",
        component("A", outs=["a"]),
        component("B", ins=["a"]),
        mode="chain",
    )
    p = project(chain)
    p.layout.extra[ORDER_KEY] = {"n-Chain": ["n-B", "n-A"]}
    assert [entry["name"] for entry in matrix(p, "n-Chain")["entries"]] == ["A", "B"]


def test_assemblies_are_blocks_around_their_leaves() -> None:
    inner = assembly("Inner", component("B", ins=["a"], outs=["b"]))
    group = assembly("Group", component("A", outs=["a"]), inner)
    p = project(group, component("C", ins=["b"]))
    data = matrix(p, "n-root")
    assert [(entry["name"], entry["depth"]) for entry in data["entries"]] == [
        ("A", 1),
        ("B", 2),
        ("C", 0),
    ]
    assert [
        (block["name"], block["start"], block["end"], block["depth"])
        for block in data["blocks"]
    ] == [("Group", 0, 1, 0), ("Inner", 1, 1, 1)]
    assert cells(data) == {
        ("n-A", "n-B"): (["a"], False),
        ("n-B", "n-C"): (["b"], False),
    }


def test_drivers_are_leaves_seen_through_their_ports() -> None:
    inner = driver(
        "Inner",
        "optimization",
        component("F", ins=["x", "a"], outs=["f"]),
        config={"interface": {"inputs": ["a"], "outputs": ["f"]}},
    )
    p = project(component("Source", outs=["a"]), inner, component("Use", ins=["f"]))
    data = matrix(p, "n-root")
    assert [entry["type"] for entry in data["entries"]] == [
        "component",
        "driver",
        "component",
    ]
    assert cells(data) == {
        ("n-Source", "n-Inner"): (["a"], False),
        ("n-Inner", "n-Use"): (["f"], False),
    }


def test_unknown_levels_are_empty() -> None:
    assert matrix(sellar(), "n-S1")["entries"] == []
