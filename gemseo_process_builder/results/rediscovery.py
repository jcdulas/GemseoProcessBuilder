"""The runs and surrogates of a project read from its script (SPEC § 4.2.2).

A script holds the study only: the runs and surrogates of the project are
found again in the data of the project, hidden from the user
(``core/project_storage.py``). Projects of earlier versions kept them next to
their file, in ``<project>.runs/`` and ``<project>.surrogates/``: these are
moved into the data of the project first.
"""

from pathlib import Path

from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.model import RunRef
from gemseo_process_builder.core.model import SurrogateRef
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.model import path_of
from gemseo_process_builder.core.project_storage import RUNS
from gemseo_process_builder.core.project_storage import SURROGATES
from gemseo_process_builder.core.project_storage import move_into
from gemseo_process_builder.results.models import read_info
from gemseo_process_builder.results.surrogates import read_metadata


def move_older_data(project: Project, folder: Path, storage: Path) -> tuple[bool, bool]:
    """Move the runs and surrogates kept next to the file into the project data.

    The surrogate components using a moved model are updated.

    Args:
        project: The project read from its script.
        folder: The folder of the script.
        storage: The data of the project.

    Returns:
        Whether something was moved, and whether components use a moved model
        (the script refers to its old place until it is saved again).
    """
    name = project.metadata.name
    moved = move_into(folder / f"{name}.runs", storage / RUNS)
    models = move_into(folder / f"{name}.surrogates", storage / SURROGATES)
    moved.update(models)
    resolved = {source.resolve(): target for source, target in models.items()}
    changed = False
    for node, _ in iter_nodes(project.root):
        if not isinstance(node, ComponentNode):
            continue
        path = node.config.get("model_path")
        if isinstance(path, str) and path:
            target = resolved.get((folder / path).resolve())
            if target is not None:
                node.config["model_path"] = str(target)
                changed = True
    return bool(moved), changed


def rediscover(project: Project, storage: Path) -> None:
    """List the runs and surrogates found in the data of a project.

    A run refers to its driver by the path of its names
    (``Model.Optimizer``): the ids of the nodes change when a script is read.

    Args:
        project: The project read from the script.
        storage: The data of the project.
    """
    drivers = {
        path_of(project, node.id): node.id for node, _ in iter_nodes(project.root)
    }
    runs = storage / RUNS
    listed = {ref.id for ref in project.runs}
    for run in sorted(runs.iterdir()) if runs.is_dir() else []:
        info = read_info(run) if run.is_dir() else None
        if info is None or info.id in listed:
            continue
        project.runs.append(
            RunRef(
                id=info.id,
                driver=drivers.get(info.driver_path, info.driver),
                run_path=str(run),
            )
        )
    surrogates = storage / SURROGATES
    listed = {ref.id for ref in project.surrogates}
    for model in sorted(surrogates.glob("*.pkl")) if surrogates.is_dir() else []:
        metadata = read_metadata(model)
        if metadata is None or metadata.id in listed:
            continue
        project.surrogates.append(
            SurrogateRef(id=metadata.id, name=metadata.name, model_path=str(model))
        )
