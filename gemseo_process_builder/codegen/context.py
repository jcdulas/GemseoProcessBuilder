"""State shared while generating one script."""

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from gemseo_process_builder.codegen.conversions import Exchanges
from gemseo_process_builder.codegen.naming import NameAllocator
from gemseo_process_builder.codegen.naming import to_identifier
from gemseo_process_builder.codegen.writer import ModuleWriter
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.resolver import Resolution


class CodegenError(Exception):
    """The project cannot be turned into a script; the message is for the user."""


@dataclass
class LocalImport:
    """A class or function imported from a Python file of the project."""

    folder_constant: str
    module: str
    name: str


@dataclass
class CodegenContext:
    """What the generators share."""

    project: Project
    resolution: Resolution
    writer: ModuleWriter
    names: NameAllocator = field(default_factory=NameAllocator)
    mapping: dict[str, str] = field(default_factory=dict)
    """Discipline name of each component, by node id (for the runner)."""

    variables: dict[str, str] = field(default_factory=dict)
    """Node id of each Python variable holding a discipline (for the dry run)."""

    own_file: Path | None = None
    """The file of the script itself, when it is the project: its functions
    and classes are used without being imported."""

    typed_inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Input values typed in the diagram, by node id then global name; set
    on the disciplines in place of their defaults."""

    folders: dict[Path, str] = field(default_factory=dict)
    """Constant naming each folder holding project modules."""

    paths: dict[Path, str] = field(default_factory=dict)
    """Constant naming each other file path (wrapper descriptors…)."""

    explained: set[str] = field(default_factory=set)
    """Concepts already explained by a comment."""

    scenarios: dict[str, str] = field(default_factory=dict)
    """Name of each nested scenario, by driver id (for the runner)."""

    scenario_variables: set[str] = field(default_factory=set)
    """Variables holding a scenario instead of a discipline (BiLevel)."""

    functions: dict[str, str] = field(default_factory=dict)
    """Node id of each function building a nested driver (for the dry run)."""

    exchanges: Exchanges = field(default_factory=Exchanges)
    """Unit conversions and reshaped arrays between the disciplines."""

    def explain(self, concept: str, comment: str) -> list[str]:
        """The comment explaining a concept, only the first time."""
        if concept in self.explained:
            return []
        self.explained.add(concept)
        return [f"    # {line}" for line in comment.splitlines()]

    def _path(self, path: Path) -> str:
        """The expression of a path.

        Relative to the script when it is the project file and the path is in
        its folder, so that the folder can move.
        """
        self.writer.use("pathlib", "Path")
        if self.own_file is not None:
            folder = self.own_file.resolve().parent
            try:
                relative = path.resolve().relative_to(folder)
            except ValueError:
                pass
            else:
                here = "Path(__file__).parent"
                return f'{here} / "{relative.as_posix()}"' if relative.parts else here
        return f'Path("{path.as_posix()}")'

    def path_constant(self, path: Path, suffix: str) -> str:
        """A constant holding a file path, like ``SOLVER_WRAPPER``."""
        if path not in self.paths:
            stem = path.name.split(".")[0]
            constant = self.names.allocate(f"{to_identifier(stem).upper()}_{suffix}")
            self.paths[path] = constant
            self.writer.constants.append(f"{constant} = {self._path(path)}")
        return self.paths[path]

    def local_import(self, path: Path, name: str) -> LocalImport:
        """Import ``name`` from a Python file inside a generated function."""
        if not path.stem.isidentifier():
            msg = (
                f"{path.name} cannot be imported: rename it with letters, digits "
                "and underscores only."
            )
            raise CodegenError(msg)
        folder = path.parent
        if folder not in self.folders:
            constant = self.names.allocate(
                to_identifier(folder.name).upper() + "_FOLDER"
            )
            self.folders[folder] = constant
            self.writer.constants.append(f"{constant} = {self._path(folder)}")
        return LocalImport(self.folders[folder], path.stem, name)
