"""The surrogate models of a project (SPEC § 7.4).

Each surrogate is stored in ``<project>.surrogates/`` as two files:
``<name>.pkl``, the trained GEMSEO regression model (only loaded by the worker
and the runner), and ``<name>.json``, its metadata: source run, variables,
algorithm, settings, quality and dates. The project lists its surrogates
(``Project.surrogates``); like the runs, the list is not part of the undo
history.
"""

import os
import shutil
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import ValidationError

from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.core.ids import new_id
from gemseo_process_builder.core.model import SurrogateRef

METADATA_VERSION = 1


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SurrogateVariable(_Model):
    """An input or an output of a surrogate."""

    name: str
    size: int = 1
    lower: list[float] = []
    upper: list[float] = []
    """For inputs: the range of the training data (outside, it extrapolates)."""

    default: list[float] = []
    """For inputs: the center of the training data."""


class OutputQuality(_Model):
    """The quality of an output, one value per component."""

    r2: list[float | None] = []
    rmse: list[float | None] = []
    r2_cv: list[float | None] = []
    rmse_cv: list[float | None] = []


class SourceRun(_Model):
    """The run a surrogate was trained on."""

    id: str
    name: str = ""
    driver_name: str = ""
    deleted: bool = False
    """The run was deleted since: the surrogate stays usable."""


class SurrogateMetadata(_Model):
    """The content of ``<name>.json``."""

    schema_version: int = METADATA_VERSION
    id: str
    name: str
    algorithm: str
    settings: dict[str, Any] = {}
    source: SourceRun
    inputs: list[SurrogateVariable]
    outputs: list[SurrogateVariable]
    n_samples: int
    n_folds: int
    quality: dict[str, OutputQuality] = {}
    created: str
    updated: str

    def summary(self) -> str:
        """What the surrogate is, in one line (for the generated scripts)."""
        inputs = ", ".join(variable.name for variable in self.inputs)
        outputs = ", ".join(variable.name for variable in self.outputs)
        source = self.source.name or self.source.id
        return (
            f"{self.algorithm} trained on {self.n_samples} samples of the run "
            f"{source}: ({inputs}) -> ({outputs})"
        )


def metadata_ports(metadata: SurrogateMetadata) -> list[dict[str, Any]]:
    """The ports of a surrogate component, as introspection gives them."""

    def bounds(values: list[float]) -> str:
        texts = [f"{value:.4g}" for value in values]
        return texts[0] if len(texts) == 1 else f"[{', '.join(texts)}]"

    ports: list[dict[str, Any]] = [
        {
            "local_name": item.name,
            "direction": "in",
            "dtype": "float",
            "shape": [item.size],
            "default": item.default or None,
            "description": f"Trained between {bounds(item.lower)} and "
            f"{bounds(item.upper)}"
            if item.lower
            else "",
        }
        for item in metadata.inputs
    ]
    ports += [
        {
            "local_name": item.name,
            "direction": "out",
            "dtype": "float",
            "shape": [item.size],
        }
        for item in metadata.outputs
    ]
    return ports


class SurrogateStoreError(Exception):
    """A surrogate cannot be stored or changed; the message is for the user."""


def metadata_path(model_path: Path) -> Path:
    """The metadata file of a model file."""
    return model_path.with_suffix(".json")


def read_metadata(model_path: Path) -> SurrogateMetadata | None:
    """The metadata of a model file, or ``None`` if it is missing or unreadable."""
    try:
        text = metadata_path(model_path).read_text(encoding="utf-8")
        return SurrogateMetadata.model_validate_json(text)
    except (OSError, ValidationError):
        return None


def write_metadata(model_path: Path, metadata: SurrogateMetadata) -> None:
    """Write the metadata of a model file."""
    text = metadata.model_dump_json(indent=2) + "\n"
    metadata_path(model_path).write_text(text, encoding="utf-8", newline="\n")


def now() -> str:
    """The current time, as stored in the metadata."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def file_name(name: str) -> str:
    """A file name for a surrogate name."""
    cleaned = "".join(char if char.isalnum() or char in "-_" else "_" for char in name)
    return cleaned.strip("_") or "surrogate"


class SurrogateStore:
    """The surrogates of the current project."""

    def __init__(self, session: ProjectSession) -> None:
        self.session = session

    def folder(self) -> Path:
        """The folder holding the surrogates of the project."""
        return self.session.folder / f"{self.session.name}.surrogates"

    def training_file(self) -> Path:
        """A new file where the worker pickles a model being trained."""
        return self.folder() / ".training" / f"{new_id('s')}.pkl"

    def model_path(self, ref: SurrogateRef) -> Path:
        """The model file of a listed surrogate."""
        path = Path(ref.model_path)
        return path if path.is_absolute() else self.session.folder / path

    def _relative(self, path: Path) -> str:
        try:
            return Path(os.path.relpath(path, self.session.folder)).as_posix()
        except ValueError:
            return str(path)

    def ref(self, surrogate_id: str) -> SurrogateRef:
        """A listed surrogate."""
        for ref in self.session.project.surrogates:
            if ref.id == surrogate_id:
                return ref
        msg = f"The surrogate {surrogate_id} is not in the project."
        raise SurrogateStoreError(msg)

    def entries(self) -> list[dict[str, Any]]:
        """The listed surrogates with their metadata; missing files are flagged."""
        entries = []
        for ref in self.session.project.surrogates:
            path = self.model_path(ref)
            metadata = read_metadata(path)
            entry: dict[str, Any] = {
                "id": ref.id,
                "name": ref.name,
                "model_path": str(path),
                "missing": metadata is None or not path.is_file(),
            }
            if metadata is not None:
                entry["metadata"] = metadata.model_dump(mode="json")
            entries.append(entry)
        return entries

    def save(
        self, trained: Path, metadata: SurrogateMetadata, replace: str = ""
    ) -> Path:
        """Store a trained model with its metadata; return the model file.

        Args:
            trained: The model pickled by the worker (see ``training_file``).
            metadata: Its metadata; the name gives the file name.
            replace: The id of a surrogate to replace (retraining).

        Raises:
            SurrogateStoreError: When the name is taken or the model is missing.
        """
        if not trained.is_file():
            msg = "The trained model is missing: train the surrogate again."
            raise SurrogateStoreError(msg)
        for ref in self.session.project.surrogates:
            if ref.name == metadata.name and ref.id != replace:
                msg = f"A surrogate is already named {metadata.name}."
                raise SurrogateStoreError(msg)
        old = self.ref(replace) if replace else None
        previous = read_metadata(self.model_path(old)) if old is not None else None
        path = self.folder() / f"{file_name(metadata.name)}.pkl"
        if old is not None and self.model_path(old) != path:
            self._remove_files(self.model_path(old))
        path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(trained, path)
        if old is not None:
            metadata.id = old.id
            metadata.created = previous.created if previous else metadata.created
            old.name = metadata.name
            old.model_path = self._relative(path)
        else:
            self.session.project.surrogates.append(
                SurrogateRef(
                    id=metadata.id, name=metadata.name, model_path=self._relative(path)
                )
            )
        write_metadata(path, metadata)
        self.session.set_dirty()
        return path

    def discard_training(self) -> None:
        """Remove the models trained but not saved."""
        shutil.rmtree(self.folder() / ".training", ignore_errors=True)

    @staticmethod
    def _remove_files(path: Path) -> None:
        for file in (path, metadata_path(path)):
            file.unlink(missing_ok=True)

    def delete(self, surrogate_id: str) -> None:
        """Remove a surrogate from the project and delete its files."""
        ref = self.ref(surrogate_id)
        self.session.project.surrogates.remove(ref)
        self.session.set_dirty()
        self._remove_files(self.model_path(ref))

    def source_deleted(self, run_id: str) -> int:
        """Flag the surrogates trained on a deleted run; return how many."""
        flagged = 0
        for ref in self.session.project.surrogates:
            path = self.model_path(ref)
            metadata = read_metadata(path)
            if metadata is not None and metadata.source.id == run_id:
                metadata.source.deleted = True
                write_metadata(path, metadata)
                flagged += 1
        return flagged
