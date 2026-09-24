"""Small directed graph algorithms used by the coupling resolver."""

from collections.abc import Iterable
from collections.abc import Mapping


def strongly_connected_components(
    nodes: Iterable[str], edges: Mapping[str, Iterable[str]]
) -> list[list[str]]:
    """Tarjan's algorithm, iterative, keeping the given node order.

    Args:
        nodes: The nodes, in display order.
        edges: The successors of each node.

    Returns:
        The components; each one lists its nodes in display order.
    """
    order = {node: index for index, node in enumerate(nodes)}
    index_of: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    counter = 0

    for root in order:
        if root in index_of:
            continue
        work: list[tuple[str, list[str]]] = [
            (root, sorted(edges.get(root, ()), key=lambda n: order.get(n, -1)))
        ]
        index_of[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, successors = work[-1]
            if successors:
                successor = successors.pop(0)
                if successor not in order:
                    continue
                if successor not in index_of:
                    index_of[successor] = low[successor] = counter
                    counter += 1
                    stack.append(successor)
                    on_stack.add(successor)
                    work.append(
                        (
                            successor,
                            sorted(
                                edges.get(successor, ()),
                                key=lambda n: order.get(n, -1),
                            ),
                        )
                    )
                elif successor in on_stack:
                    low[node] = min(low[node], index_of[successor])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index_of[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(sorted(component, key=order.__getitem__))
    return components


def feedback_edges(
    nodes: list[str], edges: Mapping[str, Iterable[str]]
) -> set[tuple[str, str]]:
    """The edges going backwards in display order inside a loop.

    Only edges between nodes of the same strongly connected component are
    feedback edges; a self-loop is one too.
    """
    position = {node: index for index, node in enumerate(nodes)}
    component_of: dict[str, int] = {}
    for number, component in enumerate(strongly_connected_components(nodes, edges)):
        for node in component:
            component_of[node] = number
    feedback = set()
    for source, targets in edges.items():
        for target in targets:
            if (
                source in position
                and target in position
                and component_of.get(source) == component_of.get(target)
                and position[target] <= position[source]
            ):
                feedback.add((source, target))
    return feedback


def execution_order(nodes: list[str], edges: Mapping[str, Iterable[str]]) -> list[str]:
    """The nodes sorted so that each one comes after the nodes it depends on.

    The display order is kept whenever the dependencies allow it. The nodes of
    a loop cannot be ordered: they stay in display order, together.
    """
    position = {node: index for index, node in enumerate(nodes)}
    components = strongly_connected_components(nodes, edges)
    component_of = {
        node: number
        for number, component in enumerate(components)
        for node in component
    }
    waiting_for = [0] * len(components)
    successors: list[set[int]] = [set() for _ in components]
    for source, targets in edges.items():
        for target in targets:
            if source not in position or target not in position:
                continue
            first, second = component_of[source], component_of[target]
            if first != second and second not in successors[first]:
                successors[first].add(second)
                waiting_for[second] += 1
    ready = [number for number in range(len(components)) if not waiting_for[number]]
    ordered: list[str] = []
    while ready:
        ready.sort(key=lambda number: position[components[number][0]])
        number = ready.pop(0)
        ordered.extend(components[number])
        for successor in successors[number]:
            waiting_for[successor] -= 1
            if not waiting_for[successor]:
                ready.append(successor)
    return ordered
