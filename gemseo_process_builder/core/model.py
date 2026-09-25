"""The project data model (SPEC § 4).

A project is a tree of nodes rooted at an assembly named ``Model``:

- components are disciplines with input and output ports;
- assemblies and drivers are containers with children.

Links between ports are stored at the project level and reference nodes by id and
ports by local name, so renaming a node never breaks a link. Everything visual
(positions, expanded containers, zoom) lives in ``Project.layout``.
"""

import re
from collections.abc import Iterator
from datetime import UTC
from datetime import datetime
from typing import Annotated
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from gemseo_process_builder import __version__
from gemseo_process_builder.core.ids import new_id

CURRENT_SCHEMA_VERSION = 1

NODE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
"""Node names: a letter followed by letters, digits or underscores."""

ComponentKind = Literal[
    "analytic", "python_function", "python_class", "executable", "surrogate"
]
DriverKind = Literal["mda", "doe", "optimization", "parametric"]
AssemblyMode = Literal["auto", "chain", "parallel", "mda"]
DType = Literal["float", "int", "complex", "str", "path", "object"]
Direction = Literal["in", "out"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def _check_node_name(name: str) -> str:
    if not NODE_NAME_PATTERN.match(name):
        msg = (
            f"Invalid name {name!r}: use a letter followed by letters, digits "
            "or underscores."
        )
        raise ValueError(msg)
    return name


class Port(_Model):
    """An input or output variable of a component."""

    local_name: str
    """The name used by the discipline itself."""

    direction: Direction
    dtype: DType = "float"
    shape: list[int] = []
    """``[]`` for a scalar, ``[n]`` for a vector, ``[n, m, …]`` for arrays."""

    shape_known: bool = True
    unit: str | None = None
    """A pint unit; ``""`` means dimensionless and ``None`` means unknown."""

    default: Any = None
    """The default value as JSON data."""

    default_text: str | None = None
    """The default value as typed by the user, kept for readable generated code."""

    description: str = ""
    global_name: str | None = None
    """An explicit global name set by the user; ``None`` uses the default rules."""

    missing: bool = False
    """Whether the port disappeared at the last introspection while still used."""

    convert_units: bool = True
    """For an input coupled by name to an output in another unit: whether the
    value is converted (explicit links have their own option)."""

    flatten: bool = False
    """For an N-D array: whether it is exchanged as a 1-D vector (GEMSEO's MDAs
    and design spaces handle 1-D arrays only), reshaped for the component."""

    @field_validator("local_name", "global_name")
    @classmethod
    def _check_port_name(cls, name: str | None) -> str | None:
        if name is not None and (not name or ":" in name):
            msg = f"Invalid variable name {name!r}: it must be non-empty, without ':'."
            raise ValueError(msg)
        return name


class _NodeBase(_Model):
    id: str = Field(default_factory=lambda: new_id("n"))
    name: str
    description: str = ""

    _check_name = field_validator("name")(_check_node_name)


class ComponentNode(_NodeBase):
    """A discipline."""

    type: Literal["component"] = "component"
    kind: ComponentKind
    config: dict[str, Any] = {}
    """Kind-specific configuration; keys ending with ``_path`` are file paths."""

    ports: list[Port] = []
    isolated: bool = False
    """Whether the ports get a namespace prefix (SPEC § 5.1, rule 6)."""

    @model_validator(mode="after")
    def _check_unique_ports(self) -> "ComponentNode":
        seen: set[tuple[str, str]] = set()
        for port in self.ports:
            key = (port.local_name, port.direction)
            if key in seen:
                msg = (
                    f"{self.name} has two {port.direction}puts named "
                    f"{port.local_name!r}."
                )
                raise ValueError(msg)
            seen.add(key)
        return self

    def port(self, local_name: str, direction: Direction) -> Port | None:
        """Return a port by name and direction."""
        for port in self.ports:
            if port.local_name == local_name and port.direction == direction:
                return port
        return None


class _ContainerBase(_NodeBase):
    children: list["Node"] = []

    @model_validator(mode="after")
    def _check_unique_children(self) -> "_ContainerBase":
        names = [child.name for child in self.children]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            msg = f"{self.name} has several children named {', '.join(duplicates)}."
            raise ValueError(msg)
        return self


class AssemblyNode(_ContainerBase):
    """A group of nodes executed as a chain, in parallel or with an MDA."""

    type: Literal["assembly"] = "assembly"
    mode: AssemblyMode = "auto"
    mda_settings: dict[str, Any] = {}
    isolated: bool = False
    transparent: bool = False
    """Whether the children are flattened into the parent driver (SPEC § 6.1)."""


class DriverNode(_ContainerBase):
    """An MDA, DOE, optimization or parametric study driving its children."""

    type: Literal["driver"] = "driver"
    kind: DriverKind
    config: dict[str, Any] = {}
    """Driver configuration (design space, objectives, algorithm, …)."""


Node = Annotated[ComponentNode | AssemblyNode | DriverNode, Field(discriminator="type")]
ContainerNode = AssemblyNode | DriverNode


class Endpoint(_Model):
    """One end of a link: a node and one of its ports."""

    node: str
    port: str


class Link(_Model):
    """An explicit link from an output port to an input port."""

    id: str = Field(default_factory=lambda: new_id("l"))
    source: Endpoint
    target: Endpoint
    convert_units: bool = True


class Metadata(_Model):
    """Descriptive information about the project."""

    name: str = "Untitled"
    description: str = ""
    created: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    gpb_version: str = __version__


class ProjectSettings(_Model):
    """Settings stored in the project."""

    catalog_paths: list[str] = []
    runs_dir: str | None = None
    """Folder of the runs; by default ``<project name>.runs`` next to the file."""


class SurrogateRef(_Model):
    """A surrogate model stored with the project."""

    id: str
    name: str
    model_path: str


class RunRef(_Model):
    """A run of the project, stored in its own folder."""

    id: str
    driver: str
    run_path: str


class NodeLayout(_Model):
    """Visual state of a node."""

    x: float = 0.0
    y: float = 0.0
    expanded: bool = False
    """Whether a container shows its children in place on the canvas."""

    port_display: Literal["compact", "all", "connected", "none"] = "compact"
    """How the variables are shown: counted on a card, or listed (all or the
    connected ones). ``none`` is the card of projects of version 0.1."""


class ViewTransform(_Model):
    """Zoom and pan of a view at one level of the hierarchy."""

    x: float = 0.0
    y: float = 0.0
    k: float = 1.0


class Layout(_Model):
    """Everything visual, kept apart to keep diffs of the model quiet."""

    nodes: dict[str, NodeLayout] = {}
    levels: dict[str, ViewTransform] = {}
    """Canvas zoom and pan per container id."""

    tree_expanded: list[str] = []
    extra: dict[str, Any] = {}
    """Free-form view state owned by the page."""


def _default_root() -> AssemblyNode:
    return AssemblyNode(id="n-root", name="Model")


class Project(_Model):
    """A GEMSEO Process Builder project."""

    schema_version: int = CURRENT_SCHEMA_VERSION
    metadata: Metadata = Field(default_factory=Metadata)
    settings: ProjectSettings = Field(default_factory=ProjectSettings)
    root: AssemblyNode = Field(default_factory=_default_root)
    links: list[Link] = []
    surrogates: list[SurrogateRef] = []
    runs: list[RunRef] = []
    layout: Layout = Field(default_factory=Layout)

    @model_validator(mode="after")
    def _check_unique_ids(self) -> "Project":
        ids = [node.id for node, _ in iter_nodes(self.root)]
        if len(ids) != len(set(ids)):
            msg = "Several nodes share the same id."
            raise ValueError(msg)
        return self

    def find(self, node_id: str) -> Node | None:
        """Return a node by id, or ``None``."""
        for node, _ in iter_nodes(self.root):
            if node.id == node_id:
                return node
        return None

    def parent_of(self, node_id: str) -> ContainerNode | None:
        """Return the container holding a node, or ``None`` for the root."""
        for node, parent in iter_nodes(self.root):
            if node.id == node_id:
                return parent
        return None


def iter_nodes(
    root: ContainerNode, parent: ContainerNode | None = None
) -> Iterator[tuple[Node, ContainerNode | None]]:
    """Yield every node of a tree with its parent, depth first, root first."""
    yield root, parent
    for child in root.children:
        if isinstance(child, AssemblyNode | DriverNode):
            yield from iter_nodes(child, root)
        else:
            yield child, root


def path_of(project: Project, node_id: str) -> str:
    """Return the dotted path of a node, like ``Model.Optimizer.Sellar1``."""
    names: list[str] = []
    current = project.find(node_id)
    while current is not None:
        names.append(current.name)
        current = project.parent_of(current.id)
    return ".".join(reversed(names))


_ContainerBase.model_rebuild()
AssemblyNode.model_rebuild()
DriverNode.model_rebuild()
Project.model_rebuild()
