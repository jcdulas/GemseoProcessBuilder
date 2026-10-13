"""What the component catalog contains."""

import re
from typing import Any
from typing import Literal

from pydantic import BaseModel

EntryKind = Literal["python_class", "python_function", "executable"]


class CatalogEntry(BaseModel):
    """A reusable component found in a catalog folder or an installed package."""

    kind: EntryKind
    name: str
    """The class, function or descriptor name."""

    module_path: str
    """The Python file (or the ``.gpbwrap.json`` descriptor); empty for an entry
    of an installed package."""

    attribute: str = ""
    """The class or function name in the module."""

    description: str = ""
    metadata: dict[str, Any] = {}
    """Extra information, like the units given by the ``component`` decorator."""

    module: str = ""
    """The dotted module of an entry of an installed package."""

    group: str = ""
    """The sub-section of its package in the Library."""


class ScanError(BaseModel):
    """A file that could not be scanned."""

    path: str
    message: str
    traceback: str = ""


class FileScan(BaseModel):
    """The result of scanning one file."""

    path: str
    mtime: float
    entries: list[CatalogEntry] = []
    error: ScanError | None = None


class PackageScan(BaseModel):
    """The catalog entries an installed distribution declares (SPEC § 7.6)."""

    name: str
    """The name of the distribution, as its metadata write it."""

    version: str
    stamp: float | None = None
    """For an editable install, the modification time of its declaration file."""

    entries: list[CatalogEntry] = []
    errors: list[ScanError] = []
    """A declaration that cannot be loaded, an entry malformed or not found."""

    warnings: list[str] = []
    """Unknown keys, a newer format."""


def normalized_name(name: str) -> str:
    """The name of a distribution as PEP 503 compares them."""
    return re.sub(r"[-_.]+", "-", name).lower()
