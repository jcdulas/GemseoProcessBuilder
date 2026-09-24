"""Python names derived from the names of the diagram."""

import builtins
import keyword
import re
import unicodedata

RESERVED = set(keyword.kwlist) | set(dir(builtins))


def to_identifier(name: str) -> str:
    """A ``snake_case`` identifier from a node name like ``SellarSystem``.

    Examples:
        >>> to_identifier("SellarSystem")
        'sellar_system'
        >>> to_identifier("MDA2_Wing")
        'mda2_wing'
    """
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", ascii_name)
    words = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", words)
    identifier = re.sub(r"[^0-9a-zA-Z]+", "_", words).strip("_").lower()
    identifier = re.sub(r"_+", "_", identifier)
    if not identifier or identifier[0].isdigit():
        identifier = f"node_{identifier}".rstrip("_")
    return identifier


class NameAllocator:
    """Give unique Python names, avoiding keywords, builtins and taken names."""

    def __init__(self, taken: set[str] | None = None) -> None:
        self.taken = set(RESERVED) | set(taken or ())

    def allocate(self, base: str) -> str:
        """Return ``base``, or ``base_2``, ``base_3``… if it is taken."""
        name = base if base not in self.taken else ""
        index = 2
        while not name:
            candidate = f"{base}_{index}"
            if candidate not in self.taken:
                name = candidate
            index += 1
        self.taken.add(name)
        return name
