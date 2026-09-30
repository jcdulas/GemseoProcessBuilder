"""Group and ungroup (Ctrl+G, Ctrl+Shift+G)."""

from pathlib import Path

import pytest
from builders import assembly
from builders import component
from builders import project

from gemseo_process_builder.core.commands import CommandError
from gemseo_process_builder.core.commands import parse_command
from gemseo_process_builder.core.document import Document
from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import Link
from gemseo_process_builder.core.model import NodeLayout
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.serialization import dumps

FOLDER = Path()


def sample() -> Project:
    """A -> B -> C in the model, with D in between; C, D and E in a mode="mda" G."""
    p = project(
        component("A", outs=["a"]),
        component("D", ins=["a"]),
        component("B", ins=["a"], outs=["b"]),
        assembly(
            "G",
            component("C", ins=["b"], outs=["c"]),
            component("E", ins=["c"]),
            mode="mda",
            description="loop",
        ),
    )
    p.links.append(
        Link(
            id="l-ab",
            source={"node": "n-A", "port": "a"},
            target={"node": "n-B", "port": "a"},
        )
    )
    for node_id, x, y in (("n-A", 100, 50), ("n-B", 400, 150), ("n-G", 300, 400)):
        p.layout.nodes[node_id] = NodeLayout(x=x, y=y)
    p.layout.nodes["n-C"] = NodeLayout(x=20, y=30)
    return p


def group(p: Project, ids: list[str]) -> tuple[Document, AssemblyNode]:
    document = Document(p)
    document.execute(parse_command({"type": "groupNodes", "ids": ids}))
    new = next(child for child in p.root.children if child.id not in {"n-D", "n-G"})
    assert isinstance(new, AssemblyNode)
    return document, new


def test_group_puts_the_nodes_in_a_new_assembly() -> None:
    p = sample()
    # Selected in any order: the nodes keep their order in the model.
    _, new = group(p, ["n-B", "n-A"])
    assert [child.name for child in p.root.children] == ["Group", "D", "G"]
    assert [child.name for child in new.children] == ["A", "B"]
    # At the top-left corner of the nodes; inside, the same relative positions.
    assert (p.layout.nodes[new.id].x, p.layout.nodes[new.id].y) == (100, 50)
    assert (p.layout.nodes["n-A"].x, p.layout.nodes["n-A"].y) == (0, 0)
    assert (p.layout.nodes["n-B"].x, p.layout.nodes["n-B"].y) == (300, 100)
    # Links reference nodes by id: they are unchanged.
    assert [link.id for link in p.links] == ["l-ab"]


def test_undo_of_a_group_restores_the_exact_project() -> None:
    p = sample()
    before = dumps(p, FOLDER)
    document, _ = group(p, ["n-A", "n-B"])
    document.undo()
    assert dumps(p, FOLDER) == before
    document.redo()
    document.undo()
    assert dumps(p, FOLDER) == before


def test_ungroup_moves_the_children_to_the_container() -> None:
    p = sample()
    document = Document(p)
    document.execute(parse_command({"type": "ungroupNode", "id": "n-G"}))
    assert [child.name for child in p.root.children] == ["A", "D", "B", "C", "E"]
    # The children keep their place on the canvas.
    assert (p.layout.nodes["n-C"].x, p.layout.nodes["n-C"].y) == (320, 430)
    assert "n-G" not in p.layout.nodes


def test_undo_of_an_ungroup_restores_the_assembly_and_its_properties() -> None:
    p = sample()
    before = dumps(p, FOLDER)
    document = Document(p)
    document.execute(parse_command({"type": "ungroupNode", "id": "n-G"}))
    document.undo()
    assert dumps(p, FOLDER) == before
    g = p.find("n-G")
    assert isinstance(g, AssemblyNode)
    assert (g.mode, g.description) == ("mda", "loop")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"type": "groupNodes", "ids": []}, "Select"),
        ({"type": "groupNodes", "ids": ["n-A", "n-C"]}, "same container"),
        ({"type": "groupNodes", "ids": ["n-root"]}, "root"),
        ({"type": "ungroupNode", "id": "n-A"}, "only assemblies"),
    ],
)
def test_impossible_groupings_change_nothing(data: dict, message: str) -> None:
    p = sample()
    before = dumps(p, FOLDER)
    with pytest.raises(CommandError, match=message):
        Document(p).execute(parse_command(data))
    assert dumps(p, FOLDER) == before


def test_ungroup_refuses_name_clashes() -> None:
    p = sample()
    p.root.children.append(component("C"))
    with pytest.raises(CommandError, match="already contains C"):
        Document(p).execute(parse_command({"type": "ungroupNode", "id": "n-G"}))
