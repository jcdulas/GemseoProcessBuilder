"""What a run folder says about its run: ``run.json`` (SPEC § 12.1).

The file is versioned; readers accept older versions and ignore unknown keys,
so that runs stay readable when the application evolves.
"""

from pathlib import Path
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import ValidationError

from gemseo_process_builder.core.atomic_write import write_text_atomically

RUN_INFO_VERSION = 1

RunStatus = Literal["preparing", "running", "completed", "stopped", "failed", "killed"]
FINAL_STATUSES = ("completed", "stopped", "failed", "killed")

Role = Literal["design variable", "objective", "constraint", "observable", "output"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class VariableInfo(_Model):
    """A variable of the results."""

    name: str
    size: int = 1
    role: Role
    constraint_type: Literal["eq", "ineq"] | None = None
    """For constraints: whether the variable must be zero or non-positive."""

    lower: list[float | None] = []
    upper: list[float | None] = []
    """For design variables: the bounds of each element (``None``: no bound)."""


class RunSummary(_Model):
    """The main figures of a run, computed by the runner at its end."""

    n_evaluations: int | None = None
    objective: str = ""
    best_objective: float | list[float] | None = None
    is_feasible: bool | None = None
    x_opt: dict[str, Any] = {}
    """Design variables at the optimum."""

    constraints: dict[str, Any] = {}
    """The constraint values at the optimum."""

    outputs: dict[str, Any] = {}
    """For a model or an MDA: the outputs of its single execution."""


class RunInfo(_Model):
    """The content of ``run.json``."""

    schema_version: int = RUN_INFO_VERSION
    id: str
    name: str = ""
    """A display name given by the user; the id is shown when empty."""

    driver: str
    driver_name: str
    driver_path: str = ""
    """Like ``Model.Optimizer``, as it was when the run started."""

    algorithm: str = ""
    formulation: str = ""

    status: RunStatus = "preparing"
    created: str
    started: str | None = None
    finished: str | None = None
    duration_s: float | None = None
    pid: int | None = None
    error: str | None = None
    versions: dict[str, str] = {}
    """Of the application, Python and GEMSEO."""

    summary: RunSummary = RunSummary()
    variables: list[VariableInfo] = []


RUN_FILE = "run.json"


def read_info(folder: Path) -> RunInfo | None:
    """The ``run.json`` of a folder, or ``None`` if it is missing or unreadable."""
    try:
        return RunInfo.model_validate_json((folder / RUN_FILE).read_text("utf-8"))
    except (OSError, ValidationError):
        return None


def write_info(folder: Path, info: RunInfo) -> None:
    """Write ``run.json`` (through a temporary file, so it is never half written)."""
    write_text_atomically(folder / RUN_FILE, info.model_dump_json(indent=2))
