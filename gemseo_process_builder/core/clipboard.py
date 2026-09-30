"""Copy and paste of sub-graphs (SPEC § 8.2).

A copied sub-graph holds the selected nodes with their descendants, the links
between them and their layouts. Pasting gives every node a new id, renames the
pasted nodes whose name is taken in the target container, keeps the internal
links and drops the links to nodes outside the selection.
"""

import copy
from typing import Any

from gemseo_process_builder.core.commands import CommandError
from gemseo_process_builder.core.commands import InsertNodes
from gemseo_process_builder.core.commands import NodePlacement
from gemseo_process_builder.core.commands import unique_name
from gemseo_process_builder.core.ids import new_id
from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Link
from gemseo_process_builder.core.model import NodeLayout
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.model import iter_nodes

CLIPBOARD_MIME_TYPE = "application/x-gpb-subgraph"
CLIPBOARD_FORMAT = "gpb-subgraph/1"
PASTE_OFFSET = 30.0
"""Shift of pasted nodes without a given position, to keep the originals visible."""


def extract_subgraph(project: Project, ids: list[str]) -> dict[str, Any]:
    """Return the JSON data of the selected nodes, their links and layouts.

    Selected nodes inside other selected nodes are ignored: they come with their
    ancestor. The root cannot be copied.
    """
    selected = set(ids)
    top_level: list[Any] = []
    for node, parent in iter_nodes(project.root):
        if node.id not in selected or parent is None:
            continue
        ancestor = project.parent_of(node.id)
        inside_selection = False
        while ancestor is not None:
            if ancestor.id in selected:
                inside_selection = True
                break
            ancestor = project.parent_of(ancestor.id)
        if not inside_selection:
            top_level.append(node)

    copied_ids: set[str] = set()
    for node in top_level:
        if isinstance(node, AssemblyNode | DriverNode):
            copied_ids.update(descendant.id for descendant, _ in iter_nodes(node))
        else:
            copied_ids.add(node.id)
    return {
        "format": CLIPBOARD_FORMAT,
        "nodes": [node.model_dump(mode="json") for node in top_level],
        "links": [
            link.model_dump(mode="json")
            for link in project.links
            if link.source.node in copied_ids and link.target.node in copied_ids
        ],
        "layouts": {
            node_id: layout.model_dump(mode="json")
            for node_id, layout in project.layout.nodes.items()
            if node_id in copied_ids
        },
    }


def _renew_ids(node: dict[str, Any], mapping: dict[str, str]) -> None:
    mapping[node["id"]] = new_id("n")
    node["id"] = mapping[node["id"]]
    for child in node.get("children", []):
        _renew_ids(child, mapping)


def paste_command(
    project: Project,
    data: dict[str, Any],
    parent_id: str,
    position: tuple[float, float] | None = None,
) -> InsertNodes:
    """Build the command inserting a copied sub-graph into a container.

    Args:
        project: The project receiving the nodes.
        data: The result of ``extract_subgraph``.
        parent_id: The container receiving the nodes.
        position: Where to put the top-left corner of the pasted nodes; by
            default, the nodes are shifted from their original position.

    Raises:
        CommandError: When the data is not a copied sub-graph or the target is
            not a container.
    """
    if data.get("format") != CLIPBOARD_FORMAT:
        msg = "The clipboard does not contain nodes."
        raise CommandError(msg)
    parent = project.find(parent_id)
    if not isinstance(parent, AssemblyNode | DriverNode):
        msg = "Nodes can only be pasted into an assembly or a driver."
        raise CommandError(msg)

    nodes = copy.deepcopy(data["nodes"])
    mapping: dict[str, str] = {}
    taken = {child.name for child in parent.children}
    for node in nodes:
        _renew_ids(node, mapping)
        node["name"] = unique_name(node["name"], taken)
        taken.add(node["name"])

    links = [
        Link.model_validate(
            {
                **link,
                "id": new_id("l"),
                "source": {**link["source"], "node": mapping[link["source"]["node"]]},
                "target": {**link["target"], "node": mapping[link["target"]["node"]]},
            }
        )
        for link in data["links"]
        if link["source"]["node"] in mapping and link["target"]["node"] in mapping
    ]

    layouts = {
        mapping[old_id]: NodeLayout.model_validate(layout)
        for old_id, layout in data["layouts"].items()
        if old_id in mapping
    }
    top_ids = [node["id"] for node in nodes]
    placed = [layouts[node_id] for node_id in top_ids if node_id in layouts]
    if placed:
        if position is None:
            dx = dy = PASTE_OFFSET
        else:
            dx = position[0] - min(layout.x for layout in placed)
            dy = position[1] - min(layout.y for layout in placed)
        for node_id in top_ids:
            if node_id in layouts:
                layout = layouts[node_id]
                layouts[node_id] = layout.model_copy(
                    update={"x": layout.x + dx, "y": layout.y + dy}
                )

    return InsertNodes(
        items=[NodePlacement(parent=parent_id, node=node) for node in nodes],
        links=links,
        layouts=layouts,
        label_text="Paste",
    )
