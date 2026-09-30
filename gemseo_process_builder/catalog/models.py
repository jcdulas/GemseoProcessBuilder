"""What the component catalog contains."""

from typing import Any
from typing import Literal

from pydantic import BaseModel

EntryKind = Literal["python_class", "python_function", "executable"]


class CatalogEntry(BaseModel):
    """A reusable component found in a catalog folder."""

    kind: EntryKind
    name: str
    """The class, function or descriptor name."""

    module_path: str
    """The Python file (or the ``.gpbwrap.json`` descriptor)."""

    attribute: str = ""
    """The class or function name in the module."""

    description: str = ""
    metadata: dict[str, Any] = {}
    """Extra information, like the units given by the ``component`` decorator."""


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
