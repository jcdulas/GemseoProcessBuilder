"""Editing commands (SPEC § 3.5).

The project is only modified through commands. Each command checks everything
before changing the project, so a failing command leaves it untouched, and
returns the command that undoes it along with the entities it touched.

Commands are Pydantic models discriminated by ``type``, so the page can send
them as plain JSON, like ``{"type": "renameNode", "id": "n-1", "name": "Aero"}``.
"""

from dataclasses import dataclass
from dataclasses import field
from typing import Annotated
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import TypeAdapter
from pydantic import ValidationError

from gemseo_process_builder.core.drivers import CONFIG_FIELDS
from gemseo_process_builder.core.drivers import FIELD_LABELS
from gemseo_process_builder.core.drivers import DriverConfig
from gemseo_process_builder.core.drivers import config_data
from gemseo_process_builder.core.ids import new_id
from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import ContainerNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Link
from gemseo_process_builder.core.model import Metadata
from gemseo_process_builder.core.model import Node
from gemseo_process_builder.core.model import NodeLayout
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.model import ProjectSettings
from gemseo_process_builder.core.model import ViewTransform
from gemseo_process_builder.core.model import iter_nodes

NODE_ADAPTER: TypeAdapter[Node] = TypeAdapter(Node)

EntityKey = tuple[str, str]
"""``(kind, id)`` of an entity sent to the page.

Kinds: node, link, layout, level, view, project (``metadata`` or ``settings``).
"""


class CommandError(Exception):
    """A command that cannot be applied; the project is unchanged."""


@dataclass
class Effect:
    """What applying a command did."""

    inverse: "Command"
    touched: set[EntityKey] = field(default_factory=set)
    removed: set[EntityKey] = field(default_factory=set)


# Helpers ---------------------------------------------------------------------


def _node(project: Project, node_id: str) -> Node:
    node = project.find(node_id)
    if node is None:
        msg = f"There is no node {node_id!r}."
        raise CommandError(msg)
    return node


def _container(project: Project, node_id: str) -> ContainerNode:
    node = _node(project, node_id)
    if not isinstance(node, AssemblyNode | DriverNode):
        msg = f"{node.name} cannot contain other nodes."
        raise CommandError(msg)
    return node


def _parent(project: Project, node_id: str) -> ContainerNode:
    parent = project.parent_of(node_id)
    if parent is None:
        msg = "The root of the model cannot be moved, renamed or deleted."
        raise CommandError(msg)
    return parent


def _descendant_ids(node: Node) -> list[str]:
    """The ids of a node and of everything it contains."""
    if isinstance(node, AssemblyNode | DriverNode):
        return [descendant.id for descendant, _ in iter_nodes(node)]
    return [node.id]


def unique_name(name: str, taken: set[str]) -> str:
    """Return ``name``, or ``name_1``, ``name_2``… if it is already taken."""
    if name not in taken:
        return name
    index = 1
    while f"{name}_{index}" in taken:
        index += 1
    return f"{name}_{index}"


def _check_sibling_name(container: ContainerNode, name: str, ignore: str = "") -> None:
    for child in container.children:
        if child.name == name and child.id != ignore:
            msg = f"{container.name} already contains a node named {name}."
            raise CommandError(msg)


def _validated(model: type[BaseModel], data: dict[str, Any]) -> Any:
    try:
        return model.model_validate(data)
    except ValidationError as error:
        messages = "; ".join(err["msg"] for err in error.errors())
        raise CommandError(messages) from None


def _insert_links(project: Project, links: list[Link], indices: list[int]) -> None:
    """Insert links at their former positions (or append them)."""
    if len(indices) != len(links):
        project.links.extend(links)
        return
    for index, link in sorted(zip(indices, links, strict=True), key=lambda i: i[0]):
        project.links.insert(index, link)


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @property
    def label(self) -> str:
        """A short description for the Edit menu ("Undo Rename")."""
        return "Edit"

    def apply(self, project: Project) -> Effect:  # pragma: no cover - abstract
        """Change the project and return what was done."""
        raise NotImplementedError


# Nodes -----------------------------------------------------------------------


class NodePlacement(BaseModel):
    """A node (with its descendants) to insert in a container."""

    parent: str
    index: int | None = None
    """Position among the children; ``None`` appends."""

    node: dict[str, Any]


class InsertNodes(_Command):
    """Insert nodes with their links and layouts (paste, undo of a deletion)."""

    type: Literal["insertNodes"] = "insertNodes"
    items: list[NodePlacement]
    links: list[Link] = []
    link_indices: list[int] = []
    """Positions of the links in the project list, to restore them exactly."""

    layouts: dict[str, NodeLayout] = {}
    label_text: str = "Insert"

    @property
    def label(self) -> str:
        """Menu label."""
        return self.label_text

    def apply(self, project: Project) -> Effect:
        """Insert the nodes."""
        existing = {node.id for node, _ in iter_nodes(project.root)}
        planned: list[tuple[ContainerNode, int | None, Node]] = []
        new_ids: list[str] = []
        names_by_parent: dict[str, set[str]] = {}
        for item in self.items:
            parent = _container(project, item.parent)
            try:
                node = NODE_ADAPTER.validate_python(item.node)
            except ValidationError as error:
                raise CommandError(str(error)) from None
            taken = names_by_parent.setdefault(
                parent.id, {child.name for child in parent.children}
            )
            if node.name in taken:
                msg = f"{parent.name} already contains a node named {node.name}."
                raise CommandError(msg)
            taken.add(node.name)
            ids = _descendant_ids(node)
            if existing.intersection(ids) or set(new_ids).intersection(ids):
                msg = "A node with the same id already exists."
                raise CommandError(msg)
            new_ids.extend(ids)
            planned.append((parent, item.index, node))

        all_ids = existing | set(new_ids)
        for link in self.links:
            if link.source.node not in all_ids or link.target.node not in all_ids:
                msg = "A link references a node that does not exist."
                raise CommandError(msg)

        effect = Effect(inverse=DeleteNodes(ids=[node.id for _, _, node in planned]))
        for parent, index, node in planned:
            if index is None or index >= len(parent.children):
                parent.children.append(node)
            else:
                parent.children.insert(max(index, 0), node)
            effect.touched.add(("node", parent.id))
        effect.touched.update(("node", node_id) for node_id in new_ids)
        _insert_links(project, self.links, self.link_indices)
        effect.touched.update(("link", link.id) for link in self.links)
        for node_id, layout in self.layouts.items():
            project.layout.nodes[node_id] = layout
            effect.touched.add(("layout", node_id))
        return effect


class AddNode(_Command):
    """Add a new node, renamed with a suffix if its name is taken."""

    type: Literal["addNode"] = "addNode"
    parent: str
    node: dict[str, Any]
    """At least ``type``, ``name`` and ``kind`` (components and drivers)."""

    position: NodeLayout | None = None

    @property
    def label(self) -> str:
        """Menu label."""
        return f"Add {self.node.get('name', 'node')}"

    def apply(self, project: Project) -> Effect:
        """Add the node."""
        parent = _container(project, self.parent)
        data = {"id": new_id("n"), **self.node}
        data["name"] = unique_name(
            str(data.get("name", "Node")), {child.name for child in parent.children}
        )
        layouts = {data["id"]: self.position} if self.position else {}
        effect = InsertNodes(
            items=[NodePlacement(parent=parent.id, node=data)], layouts=layouts
        ).apply(project)
        return effect


class DeleteNodes(_Command):
    """Delete nodes, their descendants, their links and their layouts."""

    type: Literal["deleteNodes"] = "deleteNodes"
    ids: list[str]

    @property
    def label(self) -> str:
        """Menu label."""
        return "Delete" if len(self.ids) != 1 else "Delete node"

    def apply(self, project: Project) -> Effect:
        """Delete the nodes."""
        nodes = [_node(project, node_id) for node_id in self.ids]
        parents = [_parent(project, node_id) for node_id in self.ids]
        # Ignore nodes already deleted with a selected ancestor.
        removed_ids: set[str] = set()
        roots: list[tuple[Node, ContainerNode]] = []
        for node, parent in sorted(
            zip(nodes, parents, strict=True),
            key=lambda item: len(_descendant_ids(item[0])),
            reverse=True,
        ):
            if node.id in removed_ids:
                continue
            removed_ids.update(_descendant_ids(node))
            roots.append((node, parent))

        # Remember where each node was, in increasing index order for reinsertion.
        placements = sorted(
            ((parent.children.index(node), parent, node) for node, parent in roots),
            key=lambda item: item[0],
        )
        indexed_links = [
            (index, link)
            for index, link in enumerate(project.links)
            if link.source.node in removed_ids or link.target.node in removed_ids
        ]
        links = [link for _, link in indexed_links]
        layouts = {
            node_id: project.layout.nodes[node_id]
            for node_id in removed_ids
            if node_id in project.layout.nodes
        }
        inverse = InsertNodes(
            items=[
                NodePlacement(
                    parent=parent.id, index=index, node=node.model_dump(mode="json")
                )
                for index, parent, node in placements
            ],
            links=links,
            link_indices=[index for index, _ in indexed_links],
            layouts=layouts,
            label_text=self.label,
        )

        effect = Effect(inverse=inverse)
        for _, parent, node in placements:
            parent.children.remove(node)
            effect.touched.add(("node", parent.id))
        link_ids = {link.id for link in links}
        project.links = [link for link in project.links if link.id not in link_ids]
        for node_id in layouts:
            del project.layout.nodes[node_id]
            effect.removed.add(("layout", node_id))
        effect.removed.update(("node", node_id) for node_id in removed_ids)
        effect.removed.update(("link", link_id) for link_id in link_ids)
        return effect


class RenameNode(_Command):
    """Rename a node."""

    type: Literal["renameNode"] = "renameNode"
    id: str
    name: str

    @property
    def label(self) -> str:
        """Menu label."""
        return "Rename"

    def apply(self, project: Project) -> Effect:
        """Rename the node."""
        node = _node(project, self.id)
        parent = _parent(project, self.id)
        _check_sibling_name(parent, self.name, ignore=self.id)
        old_name = node.name
        try:
            node.name = self.name
        except ValidationError as error:
            raise CommandError(error.errors()[0]["msg"]) from None
        return Effect(
            inverse=RenameNode(id=self.id, name=old_name), touched={("node", self.id)}
        )


class Placement(BaseModel):
    """Where to put a node: a parent and a position among its children."""

    id: str
    parent: str
    index: int | None = None


class ReparentNodes(_Command):
    """Move nodes to other containers (drag and drop in the tree)."""

    type: Literal["reparentNodes"] = "reparentNodes"
    placements: list[Placement]

    @property
    def label(self) -> str:
        """Menu label."""
        return "Move"

    def apply(self, project: Project) -> Effect:
        """Move the nodes."""
        moves: list[tuple[Node, ContainerNode, ContainerNode, int | None]] = []
        for placement in self.placements:
            node = _node(project, placement.id)
            old_parent = _parent(project, placement.id)
            new_parent = _container(project, placement.parent)
            if new_parent.id in _descendant_ids(node):
                msg = f"{node.name} cannot be moved inside itself."
                raise CommandError(msg)
            if new_parent is not old_parent:
                _check_sibling_name(new_parent, node.name)
            moves.append((node, old_parent, new_parent, placement.index))

        inverse = ReparentNodes(
            placements=sorted(
                (
                    Placement(
                        id=node.id,
                        parent=old_parent.id,
                        index=old_parent.children.index(node),
                    )
                    for node, old_parent, _, _ in moves
                ),
                key=lambda placement: placement.index or 0,
            )
        )
        effect = Effect(inverse=inverse)
        for node, old_parent, new_parent, index in moves:
            old_parent.children.remove(node)
            if index is None or index >= len(new_parent.children):
                new_parent.children.append(node)
            else:
                new_parent.children.insert(max(index, 0), node)
            effect.touched.update({("node", old_parent.id), ("node", new_parent.id)})
            effect.touched.add(("node", node.id))
        return effect


EDITABLE_PROPERTIES = {
    "description",
    "config",
    "mode",
    "mda_settings",
    "isolated",
    "transparent",
    "kind",
}


class SetNodeProperties(_Command):
    """Change properties of a node (not its name, children or ports)."""

    type: Literal["setNodeProperties"] = "setNodeProperties"
    id: str
    values: dict[str, Any]
    label_text: str = "Change properties"

    @property
    def label(self) -> str:
        """Menu label."""
        return self.label_text

    def apply(self, project: Project) -> Effect:
        """Change the properties."""
        unknown = set(self.values) - EDITABLE_PROPERTIES
        if unknown:
            msg = f"These properties cannot be changed: {', '.join(sorted(unknown))}."
            raise CommandError(msg)
        node = _node(project, self.id)
        data = node.model_dump()
        missing = set(self.values) - set(data)
        if missing:
            msg = f"{node.name} has no property {', '.join(sorted(missing))}."
            raise CommandError(msg)
        old_values = {key: data[key] for key in self.values}
        updated = _validated(type(node), {**data, **self.values})
        for key in self.values:
            setattr(node, key, getattr(updated, key))
        return Effect(
            inverse=SetNodeProperties(
                id=self.id, values=old_values, label_text=self.label_text
            ),
            touched={("node", self.id)},
        )


class SetPorts(_Command):
    """Replace the ports of a component."""

    type: Literal["setPorts"] = "setPorts"
    id: str
    ports: list[Port]

    @property
    def label(self) -> str:
        """Menu label."""
        return "Change variables"

    def apply(self, project: Project) -> Effect:
        """Replace the ports."""
        node = _node(project, self.id)
        if not isinstance(node, ComponentNode):
            msg = f"{node.name} has no variables of its own."
            raise CommandError(msg)
        updated = _validated(
            ComponentNode,
            {**node.model_dump(), "ports": [p.model_dump() for p in self.ports]},
        )
        old_ports = node.ports
        node.ports = updated.ports
        return Effect(
            inverse=SetPorts(id=self.id, ports=old_ports), touched={("node", self.id)}
        )


class SetGlobalName(_Command):
    """Give a port an explicit global name, or restore the automatic one."""

    type: Literal["setGlobalName"] = "setGlobalName"
    id: str
    port: str
    direction: Literal["in", "out"]
    global_name: str | None

    @property
    def label(self) -> str:
        """Menu label."""
        return "Rename variable globally"

    def apply(self, project: Project) -> Effect:
        """Change the global name."""
        node = _node(project, self.id)
        if not isinstance(node, ComponentNode):
            msg = f"{node.name} has no variables of its own."
            raise CommandError(msg)
        port = node.port(self.port, self.direction)
        if port is None:
            msg = f"{node.name} has no {self.direction}put {self.port}."
            raise CommandError(msg)
        old = port.global_name
        try:
            port.global_name = self.global_name or None
        except ValidationError as error:
            raise CommandError(error.errors()[0]["msg"]) from None
        return Effect(
            inverse=SetGlobalName(
                id=self.id, port=self.port, direction=self.direction, global_name=old
            ),
            touched={("node", self.id)},
        )


# Links -----------------------------------------------------------------------


class InsertLinks(_Command):
    """Add explicit links."""

    type: Literal["insertLinks"] = "insertLinks"
    links: list[Link]
    indices: list[int] = []
    """Positions in the project list, to restore deleted links exactly."""

    @property
    def label(self) -> str:
        """Menu label."""
        return "Add link" if len(self.links) == 1 else "Add links"

    def apply(self, project: Project) -> Effect:
        """Add the links."""
        existing = {link.id for link in project.links}
        for link in self.links:
            if link.id in existing:
                msg = "A link with the same id already exists."
                raise CommandError(msg)
            source = _node(project, link.source.node)
            target = _node(project, link.target.node)
            # Ports are only checked once known (after introspection).
            if (
                isinstance(source, ComponentNode)
                and source.ports
                and source.port(link.source.port, "out") is None
            ):
                msg = f"{source.name} has no output {link.source.port}."
                raise CommandError(msg)
            if (
                isinstance(target, ComponentNode)
                and target.ports
                and target.port(link.target.port, "in") is None
            ):
                msg = f"{target.name} has no input {link.target.port}."
                raise CommandError(msg)
        _insert_links(project, self.links, self.indices)
        return Effect(
            inverse=DeleteLinks(ids=[link.id for link in self.links]),
            touched={("link", link.id) for link in self.links},
        )


class AddLink(_Command):
    """Add one explicit link from an output to an input."""

    type: Literal["addLink"] = "addLink"
    source: dict[str, str]
    target: dict[str, str]

    @property
    def label(self) -> str:
        """Menu label."""
        return "Add link"

    def apply(self, project: Project) -> Effect:
        """Add the link."""
        link = _validated(Link, {"source": self.source, "target": self.target})
        return InsertLinks(links=[link]).apply(project)


class DeleteLinks(_Command):
    """Delete explicit links."""

    type: Literal["deleteLinks"] = "deleteLinks"
    ids: list[str]

    @property
    def label(self) -> str:
        """Menu label."""
        return "Delete link" if len(self.ids) == 1 else "Delete links"

    def apply(self, project: Project) -> Effect:
        """Delete the links."""
        by_id = {link.id: link for link in project.links}
        missing = [link_id for link_id in self.ids if link_id not in by_id]
        if missing:
            msg = f"There is no link {missing[0]!r}."
            raise CommandError(msg)
        indexed = [
            (index, link)
            for index, link in enumerate(project.links)
            if link.id in self.ids
        ]
        removed = [link for _, link in indexed]
        project.links = [link for link in project.links if link.id not in self.ids]
        return Effect(
            inverse=InsertLinks(links=removed, indices=[index for index, _ in indexed]),
            removed={("link", link.id) for link in removed},
        )


# Layout ----------------------------------------------------------------------


class Position(BaseModel):
    """A node position."""

    x: float
    y: float


class MoveNodes(_Command):
    """Move nodes on the canvas."""

    type: Literal["moveNodes"] = "moveNodes"
    positions: dict[str, Position | None]
    """New positions; ``None`` removes the layout entry (used by undo)."""

    @property
    def label(self) -> str:
        """Menu label."""
        return "Move"

    def apply(self, project: Project) -> Effect:
        """Move the nodes."""
        for node_id in self.positions:
            _node(project, node_id)
        layouts = project.layout.nodes
        old: dict[str, Position | None] = {
            node_id: (
                Position(x=layouts[node_id].x, y=layouts[node_id].y)
                if node_id in layouts
                else None
            )
            for node_id in self.positions
        }
        effect = Effect(inverse=MoveNodes(positions=old))
        for node_id, position in self.positions.items():
            if position is None:
                layouts.pop(node_id, None)
            else:
                layouts[node_id] = layouts.get(node_id, NodeLayout()).model_copy(
                    update={"x": position.x, "y": position.y}
                )
            effect.touched.add(("layout", node_id))
        return effect


class SetLayout(_Command):
    """Change view state: node layouts, level zooms, tree and free view state.

    These changes are usually not undoable (zoom, expanded containers).
    """

    type: Literal["setLayout"] = "setLayout"
    nodes: dict[str, dict[str, Any] | None] = {}
    """Partial ``NodeLayout`` values per node id; ``None`` removes the entry."""

    levels: dict[str, ViewTransform | None] = {}
    """Zoom and pan per container id; ``None`` removes the entry."""
    tree_expanded: list[str] | None = None
    extra: dict[str, Any] = {}

    @property
    def label(self) -> str:
        """Menu label."""
        return "Change view"

    def apply(self, project: Project) -> Effect:
        """Change the view state."""
        layout = project.layout
        new_nodes = {
            node_id: (
                None
                if values is None
                else _validated(
                    NodeLayout,
                    {**layout.nodes.get(node_id, NodeLayout()).model_dump(), **values},
                )
            )
            for node_id, values in self.nodes.items()
        }
        inverse = SetLayout(
            nodes={
                node_id: (
                    layout.nodes[node_id].model_dump()
                    if node_id in layout.nodes
                    else None
                )
                for node_id in self.nodes
            },
            levels={level: layout.levels.get(level) for level in self.levels},
            tree_expanded=(
                list(layout.tree_expanded) if self.tree_expanded is not None else None
            ),
            extra={key: layout.extra.get(key) for key in self.extra},
        )
        effect = Effect(inverse=inverse)
        for node_id, node_layout in new_nodes.items():
            if node_layout is None:
                layout.nodes.pop(node_id, None)
            else:
                layout.nodes[node_id] = node_layout
            effect.touched.add(("layout", node_id))
        for level, transform in self.levels.items():
            if transform is None:
                layout.levels.pop(level, None)
            else:
                layout.levels[level] = transform
            effect.touched.add(("level", level))
        if self.tree_expanded is not None:
            layout.tree_expanded = self.tree_expanded
            effect.touched.add(("view", "tree_expanded"))
        for key, value in self.extra.items():
            if value is None:
                layout.extra.pop(key, None)
            else:
                layout.extra[key] = value
            effect.touched.add(("view", f"extra.{key}"))
        return effect


class SetDriverConfig(_Command):
    """Change one field of a driver's configuration (``design_space``, …)."""

    type: Literal["setDriverConfig"] = "setDriverConfig"
    id: str
    field: str
    value: Any = None
    """The new value; ``None`` restores the default."""

    @property
    def label(self) -> str:
        """Menu label."""
        return FIELD_LABELS.get(self.field, "Change driver")

    def apply(self, project: Project) -> Effect:
        """Change the field, validating the whole configuration."""
        node = _node(project, self.id)
        if not isinstance(node, DriverNode):
            msg = f"{node.name} is not a driver."
            raise CommandError(msg)
        if self.field not in CONFIG_FIELDS:
            msg = f"Drivers have no setting {self.field}."
            raise CommandError(msg)
        data = dict(node.config)
        old_value = data.pop(self.field, None)
        if self.value is not None:
            data[self.field] = self.value
        try:
            config = DriverConfig.model_validate(data)
        except ValidationError as error:
            raise CommandError(_first_error(error)) from None
        node.config = config_data(config)
        return Effect(
            inverse=SetDriverConfig(id=self.id, field=self.field, value=old_value),
            touched={("node", self.id)},
        )


def _first_error(error: ValidationError) -> str:
    """A short message from the first error of a validation."""
    first = error.errors(include_url=False)[0]
    location = ".".join(str(part) for part in first["loc"])
    message = str(first["msg"]).removeprefix("Value error, ")
    return f"{location}: {message}" if location else message


# Project ---------------------------------------------------------------------


class SetProjectSettings(_Command):
    """Change the project metadata (name, description) or settings."""

    type: Literal["setProjectSettings"] = "setProjectSettings"
    metadata: dict[str, Any] = {}
    settings: dict[str, Any] = {}

    @property
    def label(self) -> str:
        """Menu label."""
        return "Change project settings"

    def apply(self, project: Project) -> Effect:
        """Change the metadata and settings."""
        old_metadata = project.metadata.model_dump()
        old_settings = project.settings.model_dump()
        metadata = _validated(Metadata, {**old_metadata, **self.metadata})
        settings = _validated(ProjectSettings, {**old_settings, **self.settings})
        project.metadata = metadata
        project.settings = settings
        return Effect(
            inverse=SetProjectSettings(
                metadata={key: old_metadata[key] for key in self.metadata},
                settings={key: old_settings[key] for key in self.settings},
            ),
            touched={("project", "metadata"), ("project", "settings")},
        )


Command = Annotated[
    InsertNodes
    | AddNode
    | DeleteNodes
    | RenameNode
    | ReparentNodes
    | SetNodeProperties
    | SetPorts
    | SetDriverConfig
    | SetGlobalName
    | InsertLinks
    | AddLink
    | DeleteLinks
    | MoveNodes
    | SetLayout
    | SetProjectSettings,
    Field(discriminator="type"),
]
COMMAND_ADAPTER: TypeAdapter[Command] = TypeAdapter(Command)


def parse_command(data: dict[str, Any]) -> Command:
    """Build a command from its JSON form.

    Raises:
        CommandError: When the command is unknown or invalid.
    """
    try:
        return COMMAND_ADAPTER.validate_python(data)
    except ValidationError as error:
        raise CommandError(f"Invalid command: {error}") from None
