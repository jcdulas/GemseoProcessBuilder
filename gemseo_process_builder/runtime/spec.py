"""The description of an executable wrapper (SPEC § 7.5).

An ``ExecutableSpec`` says how to run an external code: the input files written
from templates, the command, and the rules reading the outputs. It is stored
in a reusable descriptor file ``<name>.gpbwrap.json``, whose relative paths
are relative to the descriptor itself.

This module only needs Pydantic: the application reads descriptors without
GEMSEO.
"""

import json
from pathlib import Path
from typing import Annotated
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

DESCRIPTOR_SUFFIX = ".gpbwrap.json"
STDOUT = "stdout"
"""The name reading the standard output of the command instead of a file."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PortSpec(_Model):
    """An input or an output of the wrapper."""

    name: str
    dtype: Literal["float", "int", "str", "path"] = "float"
    size: int = Field(default=1, ge=1)
    """The number of values: 1 for a scalar, more for a vector."""

    default: Any = None
    """For an input: the value used when nothing is given."""

    unit: str | None = None
    description: str = ""


class TemplateFile(_Model):
    """An input file written from a template before each run."""

    template: str = ""
    """The template file, relative to the descriptor: ``{{x}}`` or ``{{x:.6e}}``
    markers are replaced by the input values."""

    content: str | None = None
    """The template itself, instead of a file (wrappers kept in a project)."""

    target: str
    """The name of the file written in the working folder."""


class _Rule(_Model):
    variable: str
    """The output read by the rule."""

    file: str = STDOUT
    """The file of the working folder to read, or ``stdout``."""


class RegexRule(_Rule):
    """A value captured by a regular expression."""

    kind: Literal["regex"] = "regex"
    pattern: str
    group: int = 1
    occurrence: Literal["first", "last", "all"] = "first"
    """``all`` reads a vector: one value per match."""


class MarkerRule(_Rule):
    """A value on a line after a marker line, in a column."""

    kind: Literal["marker"] = "marker"
    marker: str
    line: int = 1
    """The line to read, counted from the marker line (0: the marker line)."""

    column: int = 0
    """The column to read, counted from 0; columns are split by whitespace."""


class KeyValueRule(_Rule):
    """A value on a ``key = value`` line."""

    kind: Literal["key_value"] = "key_value"
    key: str
    separator: str = "="


class TableRule(_Rule):
    """A vector read in a column of the lines after a marker."""

    kind: Literal["table"] = "table"
    marker: str
    column: int = 0
    skip: int = 0
    """Lines to skip after the marker (headers)."""

    end: str = ""
    """The line ending the table; an empty line by default."""


class FileRule(_Rule):
    """The path of a file produced by the command."""

    kind: Literal["file"] = "file"


OutputRule = Annotated[
    RegexRule | MarkerRule | KeyValueRule | TableRule | FileRule,
    Field(discriminator="kind"),
]


class ExecutableSpec(_Model):
    """How to run an external code as a discipline."""

    name: str
    command: str
    """The command line, run in the working folder. Tokens: ``{python}`` (the
    Python of the process), ``{workdir}``, ``{input_file}``, ``{output_file}``."""

    inputs: list[PortSpec] = []
    outputs: list[PortSpec] = []
    templates: list[TemplateFile] = []
    rules: list[OutputRule] = []
    input_file: str = ""
    """The file of ``{input_file}``; the target of the first template by default."""

    output_file: str = ""
    """The file of ``{output_file}``."""

    files: list[str] = []
    """Files copied in the working folder before each run, relative to the
    descriptor."""

    environment: dict[str, str] = {}
    timeout: float | None = None
    """Seconds; ``None`` waits for the command whatever its duration."""

    return_codes: list[int] = [0]
    """The return codes of a successful run."""

    error_patterns: list[str] = []
    """Regular expressions that make a run fail when found in its output."""

    workdir_root: str = ""
    """Where the working folders are created; the temporary folder by default."""

    retention: Literal["always", "on_error", "never"] = "on_error"
    """Which working folders are kept after a run."""

    vector_separator: str = " "
    """How vectors are written in the input files; ``\\n`` for one per line."""


def load_descriptor(path: Path) -> tuple[ExecutableSpec, Path]:
    """Read a descriptor; return the spec and the folder its paths refer to.

    Raises:
        ValueError: When the file is not a valid descriptor.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ExecutableSpec.model_validate(data), path.parent
    except (OSError, ValueError) as error:
        msg = f"{path.name} is not a valid wrapper descriptor: {error}"
        raise ValueError(msg) from error


def spec_data(spec: ExecutableSpec) -> dict[str, Any]:
    """The spec as JSON data, without its default values but with rule kinds."""
    data = spec.model_dump(mode="json", exclude_defaults=True)
    if spec.rules:
        data["rules"] = [
            {"kind": rule.kind, **rule.model_dump(mode="json", exclude_defaults=True)}
            for rule in spec.rules
        ]
    return data


def spec_ports(spec: ExecutableSpec) -> list[dict[str, Any]]:
    """The ports of a wrapper, as introspection gives them."""
    ports = []
    for direction, items in (("in", spec.inputs), ("out", spec.outputs)):
        for item in items:
            text = item.dtype in ("str", "path")
            ports.append(
                {
                    "local_name": item.name,
                    "direction": direction,
                    "dtype": item.dtype,
                    "shape": [] if text else [item.size],
                    "default": item.default if direction == "in" else None,
                    "unit": item.unit,
                    "description": item.description,
                }
            )
    return ports


def save_descriptor(spec: ExecutableSpec, path: Path) -> None:
    """Write a descriptor, leaving out the default values."""
    text = json.dumps(spec_data(spec), indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
