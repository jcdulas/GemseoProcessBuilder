"""Resolution of variable names and couplings (SPEC § 5).

GEMSEO couples disciplines by global variable name; the diagram also has
explicit links. The rules:

1. a port's global name is its local name, prefixed by the namespaces of the
   isolated nodes around it (``Wing:area``), unless the user overrides it;
2. an explicit link from an output ``a`` to an input ``b`` gives ``b`` the
   global name of ``a``;
3. in a scope (the root model or a driver), an output and an input with the
   same global name are coupled; an input has at most one producer.

Containers expose derived ports: the inputs of their content that are not
produced inside, and the outputs produced inside. A nested driver only exposes
the variables listed in its configuration (``config["exposed"]``).

This module is pure Python: it needs neither Qt nor GEMSEO.
"""

from dataclasses import dataclass
from dataclasses import field
from typing import Any

from gemseo_process_builder.core.graph import feedback_edges
from gemseo_process_builder.core.graph import strongly_connected_components
from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import ContainerNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Node
from gemseo_process_builder.core.model import Project

NAMESPACE_SEPARATOR = ":"


@dataclass(frozen=True)
class PortRef:
    """A port of a component."""

    node: str
    port: str
    direction: str


@dataclass
class ResolvedPort:
    """A port with its global name."""

    ref: PortRef
    global_name: str
    source: str
    """Where the global name comes from: default, namespace, link or override."""

    scope: str


@dataclass
class Coupling:
    """The producer and the consumers of a global name in a scope."""

    global_name: str
    producers: list[PortRef] = field(default_factory=list)
    consumers: list[tuple[PortRef, str]] = field(default_factory=list)
    """Consumers with how they are linked: ``implicit`` or ``explicit``."""


@dataclass
class Issue:
    """A problem found while resolving; turned into a validation message later."""

    code: str
    message: str
    node: str
    port: str = ""
    link: str = ""


@dataclass
class DerivedPorts:
    """The global names consumed and produced by a node, seen from its level."""

    inputs: set[str] = field(default_factory=set)
    outputs: set[str] = field(default_factory=set)


@dataclass
class LevelEdge:
    """A dependency between two nodes of the same level."""

    source: str
    target: str
    variables: list[dict[str, Any]]
    feedback: bool = False


@dataclass
class Resolution:
    """Everything known about the variables of a project."""

    ports: dict[PortRef, ResolvedPort] = field(default_factory=dict)
    scope_of: dict[str, str] = field(default_factory=dict)
    """The scope (root or driver id) each node belongs to."""

    couplings: dict[str, dict[str, Coupling]] = field(default_factory=dict)
    free_inputs: dict[str, list[str]] = field(default_factory=dict)
    derived: dict[str, DerivedPorts] = field(default_factory=dict)
    edges: dict[str, list[LevelEdge]] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    def global_name(self, node: str, port: str, direction: str) -> str | None:
        """The global name of a port, if it exists."""
        resolved = self.ports.get(PortRef(node, port, direction))
        return resolved.global_name if resolved else None


class _Resolver:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.result = Resolution()
        self.parent: dict[str, str] = {}
        self.components: list[ComponentNode] = []
        self.prefix: dict[str, str] = {}
        self.by_name: dict[str, list[ResolvedPort]] = {}

    # Tree ----------------------------------------------------------------------

    def walk(self, node: Node, scope: str, prefix: str) -> None:
        self.result.scope_of[node.id] = scope
        if isinstance(node, ComponentNode):
            self.prefix[node.id] = prefix + (
                node.name + NAMESPACE_SEPARATOR if node.isolated else ""
            )
            self.components.append(node)
            return
        if isinstance(node, DriverNode) and node.id != self.project.root.id:
            inner_scope, inner_prefix = node.id, ""
        else:
            inner_scope, inner_prefix = scope, prefix
        if isinstance(node, AssemblyNode) and node.isolated:
            inner_prefix += node.name + NAMESPACE_SEPARATOR
        for child in node.children:
            self.parent[child.id] = node.id
            self.walk(child, inner_scope, inner_prefix)

    def ancestor_in(self, node_id: str, container_id: str) -> str | None:
        """The child of ``container_id`` that is ``node_id`` or contains it."""
        current = node_id
        while current in self.parent:
            if self.parent[current] == container_id:
                return current
            current = self.parent[current]
        return None

    # Global names --------------------------------------------------------------

    def resolve_names(self) -> dict[PortRef, str]:
        """Give every port its global name; return the explicit link targets."""
        components = {node.id: node for node in self.components}
        for node in self.components:
            scope = self.result.scope_of[node.id]
            for port in node.ports:
                ref = PortRef(node.id, port.local_name, port.direction)
                if port.global_name:
                    name, origin = port.global_name, "override"
                elif self.prefix[node.id]:
                    name, origin = self.prefix[node.id] + port.local_name, "namespace"
                else:
                    name, origin = port.local_name, "default"
                self.result.ports[ref] = ResolvedPort(ref, name, origin, scope)

        linked: dict[PortRef, str] = {}
        for link in self.project.links:
            source_node = components.get(link.source.node)
            target_node = components.get(link.target.node)
            source = PortRef(link.source.node, link.source.port, "out")
            target = PortRef(link.target.node, link.target.port, "in")
            if source_node is None or target_node is None:
                self.issue(
                    "link_to_missing_port",
                    "A link points to a node that no longer exists.",
                    link.target.node,
                    link=link.id,
                )
                continue
            for end_node, end in ((source_node, source), (target_node, target)):
                found = end_node.port(end.port, end.direction)  # type: ignore[arg-type]
                if found is None or found.missing:
                    self.issue(
                        "link_to_missing_port",
                        f"{end_node.name} has no {end.direction}put {end.port} any "
                        "more, but a link still uses it.",
                        end_node.id,
                        end.port,
                        link.id,
                    )
            if source not in self.result.ports or target not in self.result.ports:
                continue
            if target in linked:
                self.issue(
                    "multiple_explicit_links",
                    f"{target_node.name}.{target.port} receives several links; "
                    "only the first one is used.",
                    target.node,
                    target.port,
                    link.id,
                )
                continue
            resolved_target = self.result.ports[target]
            if resolved_target.source == "override":
                linked[target] = link.id
                continue
            resolved_target.global_name = self.result.ports[source].global_name
            resolved_target.source = "link"
            linked[target] = link.id
        return linked

    # Couplings -----------------------------------------------------------------

    def resolve_couplings(self, linked: dict[PortRef, str]) -> None:
        names = {node.id: node.name for node in self.components}
        for resolved in self.result.ports.values():
            couplings = self.result.couplings.setdefault(resolved.scope, {})
            coupling = couplings.setdefault(
                resolved.global_name, Coupling(resolved.global_name)
            )
            if resolved.ref.direction == "out":
                coupling.producers.append(resolved.ref)
            else:
                kind = "explicit" if resolved.ref in linked else "implicit"
                coupling.consumers.append((resolved.ref, kind))
        for scope, couplings in self.result.couplings.items():
            free = []
            for name, coupling in couplings.items():
                if len(coupling.producers) > 1:
                    producers = ", ".join(names[ref.node] for ref in coupling.producers)
                    for ref in coupling.producers[1:]:
                        self.issue(
                            "duplicate_producer",
                            f"{name} is computed by several components ({producers}).",
                            ref.node,
                            ref.port,
                        )
                if not coupling.producers and coupling.consumers:
                    free.append(name)
            self.result.free_inputs[scope] = sorted(free)

    # Containers ----------------------------------------------------------------

    def exposed(self, driver: DriverNode) -> DerivedPorts:
        exposed = driver.config.get("exposed") or {}
        return DerivedPorts(
            set(exposed.get("inputs", [])), set(exposed.get("outputs", []))
        )

    def derive(self, node: Node) -> DerivedPorts:
        """The derived ports of a node, seen from its parent (memoized)."""
        if node.id in self.result.derived:
            return self.result.derived[node.id]
        if isinstance(node, ComponentNode):
            ports = DerivedPorts()
            for port in node.ports:
                name = self.result.ports[
                    PortRef(node.id, port.local_name, port.direction)
                ].global_name
                (ports.inputs if port.direction == "in" else ports.outputs).add(name)
        else:
            children = [self.derive(child) for child in node.children]
            produced = set().union(*(child.outputs for child in children))
            consumed = set().union(*(child.inputs for child in children))
            ports = DerivedPorts(consumed - produced, produced)
            if isinstance(node, DriverNode) and node.id != self.project.root.id:
                ports = self.exposed(node)
        self.result.derived[node.id] = ports
        return ports

    def level_edges(self, container: ContainerNode) -> None:
        """The dependencies between the children of a container."""
        children = [child.id for child in container.children]
        derived = {child.id: self.derive(child) for child in container.children}
        by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for source in children:
            for target in children:
                if source == target:
                    continue
                shared = derived[source].outputs & derived[target].inputs
                for name in sorted(shared):
                    by_pair.setdefault((source, target), []).append(
                        self.variable(name, container.id, source, target)
                    )
        successors: dict[str, list[str]] = {}
        for source, target in by_pair:
            successors.setdefault(source, []).append(target)
        feedback = feedback_edges(children, successors)
        self.result.edges[container.id] = [
            LevelEdge(source, target, variables, (source, target) in feedback)
            for (source, target), variables in by_pair.items()
        ]
        self.check_mode(container, children, successors)

    def variable(
        self, name: str, level: str, source: str, target: str
    ) -> dict[str, Any]:
        """Details of a coupled variable between two nodes of a level."""
        source_port = target_port = ""
        explicit = False
        for resolved in self.by_name.get(name, []):
            ref = resolved.ref
            if ref.direction == "out" and ref.node == source:
                source_port = ref.port
            if ref.direction == "in" and ref.node == target:
                target_port = ref.port
            if (
                ref.direction == "in"
                and resolved.source == "link"
                and self.ancestor_in(ref.node, level) == target
            ):
                explicit = True
        return {
            "name": name,
            "source_port": source_port,
            "target_port": target_port,
            "explicit": explicit,
        }

    def check_mode(
        self,
        container: ContainerNode,
        children: list[str],
        successors: dict[str, list[str]],
    ) -> None:
        if not isinstance(container, AssemblyNode):
            return
        if container.mode == "chain":
            for component in strongly_connected_components(children, successors):
                if len(component) > 1:
                    self.issue(
                        "loop_in_chain",
                        f"{container.name} runs its content as a chain, but some of "
                        "it depends on each other in a loop: an MDA is needed.",
                        container.id,
                    )
                    return
        elif container.mode == "parallel" and successors:
            self.issue(
                "dependency_in_parallel",
                f"{container.name} runs its content in parallel, but some of it "
                "uses the results of the others.",
                container.id,
            )

    def containers(self, node: Node) -> list[ContainerNode]:
        if isinstance(node, ComponentNode):
            return []
        found: list[ContainerNode] = [node]
        for child in node.children:
            found.extend(self.containers(child))
        return found

    # Helpers -------------------------------------------------------------------

    def issue(
        self, code: str, message: str, node: str, port: str = "", link: str = ""
    ) -> None:
        self.result.issues.append(Issue(code, message, node, port, link))

    def run(self) -> Resolution:
        root = self.project.root
        self.walk(root, root.id, "")
        linked = self.resolve_names()
        for resolved in self.result.ports.values():
            self.by_name.setdefault(resolved.global_name, []).append(resolved)
        self.resolve_couplings(linked)
        for container in self.containers(root):
            self.level_edges(container)
        return self.result


def resolve(project: Project) -> Resolution:
    """Resolve the global names and the couplings of a project."""
    return _Resolver(project).run()


def level_view(resolution: Resolution, project: Project, level: str) -> dict[str, Any]:
    """What the canvas needs to draw the couplings of one level (JSON data)."""
    container = project.find(level)
    if not isinstance(container, AssemblyNode | DriverNode):
        return {"level": level, "ports": {}, "edges": [], "free_inputs": []}
    ports: dict[str, Any] = {}
    for child in container.children:
        derived = resolution.derived.get(child.id, DerivedPorts())
        if isinstance(child, ComponentNode):
            ports[child.id] = {
                direction: {
                    port.local_name: resolution.global_name(
                        child.id, port.local_name, direction
                    )
                    for port in child.ports
                    if port.direction == direction
                }
                for direction in ("in", "out")
            }
        else:
            ports[child.id] = {
                "in": sorted(derived.inputs),
                "out": sorted(derived.outputs),
            }
    scope = level if isinstance(container, DriverNode) else resolution.scope_of[level]
    return {
        "level": level,
        "scope": scope,
        "ports": ports,
        "edges": [
            {
                "source": edge.source,
                "target": edge.target,
                "feedback": edge.feedback,
                "variables": edge.variables,
            }
            for edge in resolution.edges.get(level, [])
        ],
        "free_inputs": resolution.free_inputs.get(scope, []),
    }
