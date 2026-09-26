"""Merging introspected ports with the ports edited by the user."""

from typing import Any

from gemseo_process_builder.core.model import Port

USER_FIELDS = ("unit", "description", "global_name")
"""Port fields set by the user, kept when the ports are introspected again."""


def merge_ports(
    old: list[Port],
    introspected: list[dict[str, Any]],
    linked: set[tuple[str, str]],
) -> list[Port]:
    """Combine new introspection results with the current ports.

    Args:
        old: The current ports.
        introspected: The ports found by introspection, as JSON data.
        linked: ``(name, direction)`` of the ports used by explicit links.

    Returns:
        The new ports: introspected ports keep the user fields of the old port
        with the same name and direction (a unit given by introspection wins
        over an empty one) and its typed value; old ports that disappeared but
        are still linked are
        kept and marked ``missing``.
    """
    by_key = {(port.local_name, port.direction): port for port in old}
    ports: list[Port] = []
    seen: set[tuple[str, str]] = set()
    for data in introspected:
        port = Port.model_validate(data)
        key = (port.local_name, port.direction)
        seen.add(key)
        previous = by_key.get(key)
        if previous is not None:
            updates = {
                field: getattr(previous, field)
                for field in USER_FIELDS
                if getattr(previous, field) not in (None, "")
            }
            # A value typed by the user wins over the default of the discipline.
            if previous.default_text is not None:
                updates["default"] = previous.default
                updates["default_text"] = previous.default_text
            port = port.model_copy(update=updates)
        ports.append(port)
    for key, port in by_key.items():
        if key not in seen and key in linked:
            ports.append(port.model_copy(update={"missing": True}))
    return ports
