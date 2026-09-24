from pathlib import Path
from typing import Any

import pytest
from builders import assembly
from builders import component
from builders import project

from gemseo_process_builder.core.clipboard import extract_subgraph
from gemseo_process_builder.core.clipboard import paste_command
from gemseo_process_builder.core.commands import CommandError
from gemseo_process_builder.core.commands import parse_command
from gemseo_process_builder.core.document import Document
from gemseo_process_builder.core.model import Link
from gemseo_process_builder.core.model import NodeLayout
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.serialization import dumps

FOLDER = Path()


def sample() -> Project:
    p = project(
        component("A", outs=["y"]),
        assembly("G", component("B", ins=["y"], outs=["z"]), component("C", ins=["z"])),
    )
    p.links.append(
        Link(
            id="l-ab",
            source={"node": "n-A", "port": "y"},
            target={"node": "n-B", "port": "y"},
        )
    )
    p.links.append(
        Link(
            id="l-bc",
            source={"node": "n-B", "port": "z"},
            target={"node": "n-C", "port": "z"},
        )
    )
    p.layout.nodes["n-A"] = NodeLayout(x=10, y=20)
    p.layout.nodes["n-B"] = NodeLayout(x=100, y=20)
    return p


COMMANDS: list[dict[str, Any]] = [
    {
        "type": "addNode",
        "parent": "n-G",
        "node": {"type": "component", "kind": "analytic", "name": "B"},
    },
    {
        "type": "addNode",
        "parent": "n-root",
        "node": {"type": "driver", "kind": "doe", "name": "DOE"},
        "position": {"x": 5, "y": 6},
    },
    {"type": "deleteNodes", "ids": ["n-G"]},
    {"type": "deleteNodes", "ids": ["n-B", "n-A", "n-G"]},
    {"type": "renameNode", "id": "n-A", "name": "Aero"},
    {
        "type": "reparentNodes",
        "placements": [{"id": "n-A", "parent": "n-G", "index": 0}],
    },
    {
        "type": "setNodeProperties",
        "id": "n-G",
        "values": {"mode": "mda", "description": "loop"},
    },
    {
        "type": "setPorts",
        "id": "n-A",
        "ports": [{"local_name": "w", "direction": "out"}],
    },
    {
        "type": "addLink",
        "source": {"node": "n-A", "port": "y"},
        "target": {"node": "n-C", "port": "z"},
    },
    {"type": "deleteLinks", "ids": ["l-ab"]},
    {
        "type": "moveNodes",
        "positions": {"n-A": {"x": 1, "y": 2}, "n-C": {"x": 3, "y": 4}},
    },
    {
        "type": "setLayout",
        "nodes": {"n-A": {"expanded": True}},
        "levels": {"n-G": {"k": 2}},
        "tree_expanded": ["n-G"],
        "extra": {"canvas": {"level": "n-G"}},
    },
]


@pytest.mark.parametrize("data", COMMANDS, ids=lambda data: data["type"])
def test_apply_then_undo_restores_the_project(data: dict[str, Any]) -> None:
    p = sample()
    before = dumps(p, FOLDER)
    document = Document(p)
    document.execute(parse_command(data))
    assert dumps(p, FOLDER) != before
    document.undo()
    assert dumps(p, FOLDER) == before
    document.redo()
    after_redo = dumps(p, FOLDER)
    document.undo()
    assert dumps(p, FOLDER) == before
    document.redo()
    assert dumps(p, FOLDER) == after_redo


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"type": "renameNode", "id": "n-A", "name": "G"}, "already contains"),
        ({"type": "renameNode", "id": "n-A", "name": "1x"}, "Invalid name"),
        ({"type": "renameNode", "id": "n-root", "name": "X"}, "root"),
        ({"type": "deleteNodes", "ids": ["n-nope"]}, "no node"),
        (
            {"type": "reparentNodes", "placements": [{"id": "n-G", "parent": "n-G"}]},
            "inside itself",
        ),
        (
            {"type": "reparentNodes", "placements": [{"id": "n-G", "parent": "n-A"}]},
            "cannot contain",
        ),
        (
            {"type": "setNodeProperties", "id": "n-G", "values": {"mode": "fast"}},
            "Input should be",
        ),
        (
            {"type": "setNodeProperties", "id": "n-G", "values": {"name": "X"}},
            "cannot be changed",
        ),
        ({"type": "setPorts", "id": "n-G", "ports": []}, "no variables"),
        (
            {
                "type": "addLink",
                "source": {"node": "n-A", "port": "nope"},
                "target": {"node": "n-B", "port": "y"},
            },
            "no output",
        ),
        ({"type": "deleteLinks", "ids": ["l-nope"]}, "no link"),
    ],
)
def test_failing_commands_leave_the_project_untouched(
    data: dict[str, Any], message: str
) -> None:
    p = sample()
    before = dumps(p, FOLDER)
    document = Document(p)
    with pytest.raises(CommandError, match=message):
        document.execute(parse_command(data))
    assert dumps(p, FOLDER) == before
    assert document.rev == 0


def test_unknown_command() -> None:
    with pytest.raises(CommandError, match="Invalid command"):
        parse_command({"type": "explode"})


def test_add_node_renames_on_conflict() -> None:
    document = Document(sample())
    for _ in range(2):
        document.execute(
            parse_command(
                {
                    "type": "addNode",
                    "parent": "n-root",
                    "node": {"type": "component", "kind": "analytic", "name": "A"},
                }
            )
        )
    assert [child.name for child in document.project.root.children] == [
        "A",
        "G",
        "A_1",
        "A_2",
    ]


def test_deleting_a_node_removes_its_links_and_layout() -> None:
    document = Document(sample())
    changes: list[list[dict[str, Any]]] = []
    document.on_change(lambda c, rev: changes.append(c))
    document.execute(parse_command({"type": "deleteNodes", "ids": ["n-B"]}))
    assert [link.id for link in document.project.links] == []
    assert "n-B" not in document.project.layout.nodes
    deleted = {(c["kind"], c["id"]) for c in changes[0] if c["op"] == "delete"}
    assert deleted == {
        ("node", "n-B"),
        ("link", "l-ab"),
        ("link", "l-bc"),
        ("layout", "n-B"),
    }
    upserted = {(c["kind"], c["id"]) for c in changes[0] if c["op"] == "upsert"}
    assert upserted == {("node", "n-G")}


def test_changes_hold_flat_node_entities() -> None:
    document = Document(sample())
    changes: list[dict[str, Any]] = []
    document.on_change(lambda c, rev: changes.extend(c))
    document.execute(
        parse_command({"type": "renameNode", "id": "n-G", "name": "Group"})
    )
    (change,) = changes
    assert change["data"]["name"] == "Group"
    assert change["data"]["children"] == ["n-B", "n-C"]
    assert change["data"]["parent"] == "n-root"


def test_undo_limit_and_redo_cleared_by_new_commands() -> None:
    document = Document(sample(), max_undo=2)
    for name in ("X1", "X2", "X3"):
        document.execute(
            parse_command({"type": "renameNode", "id": "n-A", "name": name})
        )
    document.undo()
    document.undo()
    assert not document.undo_state()["canUndo"]
    assert document.project.find("n-A").name == "X1"  # type: ignore[union-attr]
    document.execute(parse_command({"type": "renameNode", "id": "n-A", "name": "Y"}))
    assert not document.undo_state()["canRedo"]


def test_transactions_are_one_undo_step() -> None:
    p = sample()
    before = dumps(p, FOLDER)
    document = Document(p)
    document.execute_many(
        [
            parse_command({"type": "renameNode", "id": "n-A", "name": "Aero"}),
            parse_command({"type": "deleteNodes", "ids": ["n-C"]}),
        ],
        "Refactor",
    )
    assert document.undo_state()["undoLabel"] == "Refactor"
    document.undo()
    assert dumps(p, FOLDER) == before


def test_failing_transaction_is_rolled_back() -> None:
    p = sample()
    before = dumps(p, FOLDER)
    document = Document(p)
    with pytest.raises(CommandError):
        document.execute_many(
            [
                parse_command({"type": "renameNode", "id": "n-A", "name": "Aero"}),
                parse_command({"type": "deleteNodes", "ids": ["n-missing"]}),
            ],
            "Broken",
        )
    assert dumps(p, FOLDER) == before
    assert not document.undo_state()["canUndo"]


def test_consecutive_moves_are_merged() -> None:
    now = [0.0]
    document = Document(sample(), clock=lambda: now[0])
    for x in (1, 2, 3):
        now[0] += 0.1
        document.execute(
            parse_command({"type": "moveNodes", "positions": {"n-A": {"x": x, "y": 0}}})
        )
    now[0] += 1.0
    document.execute(
        parse_command({"type": "moveNodes", "positions": {"n-A": {"x": 9, "y": 0}}})
    )
    document.undo()
    assert document.project.layout.nodes["n-A"].x == 3
    document.undo()
    assert document.project.layout.nodes["n-A"].x == 10
    assert not document.undo_state()["canUndo"]


def test_non_undoable_commands() -> None:
    document = Document(sample())
    document.execute(
        parse_command({"type": "setLayout", "levels": {"n-root": {"k": 3}}}),
        undoable=False,
    )
    assert not document.undo_state()["canUndo"]
    assert document.rev == 1


def test_copy_paste_keeps_internal_links_only() -> None:
    p = sample()
    data = extract_subgraph(p, ["n-B", "n-C", "n-G"])
    assert [node["name"] for node in data["nodes"]] == ["G"]
    assert [link["id"] for link in data["links"]] == ["l-bc"]

    document = Document(p)
    command = paste_command(p, data, "n-root", position=(500, 600))
    document.execute(command)
    pasted = p.root.children[-1]
    assert pasted.name == "G_1"
    assert pasted.id != "n-G"
    new_ids = {child.id for child in pasted.children}  # type: ignore[union-attr]
    assert len(p.links) == 3
    assert {p.links[-1].source.node, p.links[-1].target.node} == new_ids
    document.undo()
    assert [child.name for child in p.root.children] == ["A", "G"]


def test_paste_positions_and_offsets() -> None:
    p = sample()
    data = extract_subgraph(p, ["n-A"])
    at = paste_command(p, data, "n-root", position=(0, 0))
    assert next(iter(at.layouts.values())).x == 0
    shifted = paste_command(p, data, "n-root")
    assert next(iter(shifted.layouts.values())).x == 40


def test_paste_rejects_foreign_data() -> None:
    with pytest.raises(CommandError, match="does not contain nodes"):
        paste_command(sample(), {"nodes": []}, "n-root")
