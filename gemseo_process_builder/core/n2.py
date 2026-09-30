"""The N2 matrix of a level of the model (SPEC § 8.4).

The diagonal holds the leaves of the level: its components and its drivers
(a driver is a scope of its own, seen through its ports). The assemblies of
the level are hierarchy blocks around their leaves; the page collapses them by
merging their rows and columns (``static/js/lib/n2_layout.js``).

The cell of row ``i`` and column ``j`` lists the variables that entry ``i``
computes and entry ``j`` uses; between two components, with the ports they
use, like the links of the canvas. Cells below the diagonal (``i > j``) are
feedbacks: an entry uses the output of an entry placed after it.

The diagonal follows the order of the model, or the display order chosen in
the N2 view (``layout.extra["n2_order"]``), except in ``chain`` assemblies
where the order is the execution order. This module is pure Python.
"""

from typing import Any

from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import ContainerNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Node
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.resolver import DerivedPorts
from gemseo_process_builder.core.resolver import PortRef
from gemseo_process_builder.core.resolver import Resolution

ORDER_KEY = "n2_order"
"""The layout entry holding the display order: ``{container id: [child ids]}``."""


def ordered_children(project: Project, container: ContainerNode) -> list[Node]:
    """The children of a container in the order of the N2 diagonal."""
    if isinstance(container, AssemblyNode) and container.mode == "chain":
        return list(container.children)
    order: list[str] = (project.layout.extra.get(ORDER_KEY) or {}).get(container.id, [])
    rank = {node_id: index for index, node_id in enumerate(order)}
    # Children missing from the stored order keep their place at the end.
    return sorted(
        container.children,
        key=lambda child: rank.get(child.id, len(order)),
    )


def _ports(resolution: Resolution, node: Node) -> DerivedPorts:
    if isinstance(node, ComponentNode):
        ports = DerivedPorts()
        for port in node.ports:
            name = resolution.global_name(node.id, port.local_name, port.direction)
            if name is not None:
                (ports.inputs if port.direction == "in" else ports.outputs).add(name)
        return ports
    return resolution.derived.get(node.id, DerivedPorts())


def _port_names(resolution: Resolution, node: Node, direction: str) -> dict[str, str]:
    """The local name of the port using each global name, for a component."""
    if not isinstance(node, ComponentNode):
        return {}
    names = {}
    for port in node.ports:
        if port.direction == direction:
            name = resolution.global_name(node.id, port.local_name, direction)
            if name is not None:
                names[name] = port.local_name
    return names


def _variable(
    resolution: Resolution, source: Node, target: Node, name: str
) -> dict[str, Any]:
    """A coupled variable, as in the edges of ``resolver.level_view``."""
    source_port = _port_names(resolution, source, "out").get(name, "")
    target_port = _port_names(resolution, target, "in").get(name, "")
    resolved = resolution.ports.get(PortRef(target.id, target_port, "in"))
    return {
        "name": name,
        "source_port": source_port,
        "target_port": target_port,
        "explicit": resolved is not None and resolved.source == "link",
    }


def _entry(node: Node, container: ContainerNode, depth: int) -> dict[str, Any]:
    return {
        "id": node.id,
        "name": node.name,
        "type": node.type,
        "kind": getattr(node, "kind", ""),
        "parent": container.id,
        "depth": depth,
    }


def n2_matrix(project: Project, resolution: Resolution, level: str) -> dict[str, Any]:
    """The N2 matrix of a level, as JSON data for the page.

    Returns:
        ``entries`` (the diagonal), ``blocks`` (the assemblies, with the range of
        entries they hold, outer blocks first) and ``cells`` (``row``, ``col``,
        ``variables``, ``feedback``, and ``links``: each variable with its ports).
    """
    root = project.find(level)
    if not isinstance(root, AssemblyNode | DriverNode):
        return {"level": level, "entries": [], "blocks": [], "cells": []}
    entries: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    leaves: list[Node] = []

    def visit(container: ContainerNode, depth: int) -> None:
        for child in ordered_children(project, container):
            if isinstance(child, AssemblyNode) and child.children:
                block: dict[str, Any] = {
                    "id": child.id,
                    "name": child.name,
                    "mode": child.mode,
                    "parent": container.id,
                    "depth": depth,
                    "start": len(entries),
                }
                blocks.append(block)
                visit(child, depth + 1)
                block["end"] = len(entries) - 1
            else:
                entries.append(_entry(child, container, depth))
                leaves.append(child)

    visit(root, 0)
    producers: dict[str, list[int]] = {}
    consumers: dict[str, list[int]] = {}
    for index, node in enumerate(leaves):
        ports = _ports(resolution, node)
        for name in ports.outputs:
            producers.setdefault(name, []).append(index)
        for name in ports.inputs:
            consumers.setdefault(name, []).append(index)
    variables: dict[tuple[int, int], list[str]] = {}
    for name, rows in producers.items():
        for row in rows:
            for col in consumers.get(name, []):
                if row != col:
                    variables.setdefault((row, col), []).append(name)
    cells = [
        {
            "row": row,
            "col": col,
            "variables": sorted(names),
            "feedback": row > col,
            "links": [
                _variable(resolution, leaves[row], leaves[col], name)
                for name in sorted(names)
            ],
        }
        for (row, col), names in sorted(variables.items())
    ]
    return {"level": level, "entries": entries, "blocks": blocks, "cells": cells}
