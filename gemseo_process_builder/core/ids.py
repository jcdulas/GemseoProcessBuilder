"""Identifiers of project entities."""

import uuid


def new_id(prefix: str) -> str:
    """Return a new unique identifier like ``"n-3f2a9c01b7d4"``.

    Args:
        prefix: ``"n"`` for nodes, ``"l"`` for links, ``"s"`` for surrogates.
    """
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
