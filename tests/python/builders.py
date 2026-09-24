"""Helpers to build projects concisely in tests."""

from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Node
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import Project


def component(
    name: str,
    ins: list[str] | tuple[str, ...] = (),
    outs: list[str] | tuple[str, ...] = (),
    kind: str = "analytic",
    **fields: object,
) -> ComponentNode:
    """A component with ports named ``ins`` and ``outs``; its id is ``n-<name>``."""
    ports = [Port(local_name=n, direction="in") for n in ins]
    ports += [Port(local_name=n, direction="out") for n in outs]
    return ComponentNode(
        id=f"n-{name}",
        name=name,
        kind=kind,
        ports=ports,
        **fields,  # type: ignore[arg-type]
    )


def assembly(name: str, *children: Node, **fields: object) -> AssemblyNode:
    """An assembly; its id is ``n-<name>``."""
    return AssemblyNode(id=f"n-{name}", name=name, children=list(children), **fields)  # type: ignore[arg-type]


def driver(name: str, kind: str, *children: Node, **fields: object) -> DriverNode:
    """A driver; its id is ``n-<name>``."""
    return DriverNode(
        id=f"n-{name}",
        name=name,
        kind=kind,
        children=list(children),
        **fields,  # type: ignore[arg-type]
    )


def project(*children: Node) -> Project:
    """A project whose root contains ``children``."""
    return Project(
        root=AssemblyNode(id="n-root", name="Model", children=list(children))
    )
