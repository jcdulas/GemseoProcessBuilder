"""The runs and surrogates of a project read from its script (SPEC § 4.2.2).

A script holds the study only: the runs and surrogates of the project are
found again in their folders next to it, ``<project>.runs/`` and
``<project>.surrogates/``.
"""

import os
from pathlib import Path

from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.model import RunRef
from gemseo_process_builder.core.model import SurrogateRef
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.model import path_of
from gemseo_process_builder.results.models import read_info
from gemseo_process_builder.results.surrogates import read_metadata


def _relative(path: Path, folder: Path) -> str:
    try:
        return Path(os.path.relpath(path, folder)).as_posix()
    except ValueError:  # Another drive.
        return str(path)


def rediscover(project: Project, folder: Path) -> None:
    """List the runs and surrogates found next to the script of a project.

    A run refers to its driver by the path of its names
    (``Model.Optimizer``): the ids of the nodes change when a script is read.

    Args:
        project: The project read from the script.
        folder: The folder of the script.
    """
    drivers = {
        path_of(project, node.id): node.id for node, _ in iter_nodes(project.root)
    }
    runs = folder / f"{project.metadata.name}.runs"
    listed = {ref.id for ref in project.runs}
    for run in sorted(runs.iterdir()) if runs.is_dir() else []:
        info = read_info(run) if run.is_dir() else None
        if info is None or info.id in listed:
            continue
        project.runs.append(
            RunRef(
                id=info.id,
                driver=drivers.get(info.driver_path, info.driver),
                run_path=_relative(run, folder),
            )
        )
    surrogates = folder / f"{project.metadata.name}.surrogates"
    listed = {ref.id for ref in project.surrogates}
    for model in sorted(surrogates.glob("*.pkl")) if surrogates.is_dir() else []:
        metadata = read_metadata(model)
        if metadata is None or metadata.id in listed:
            continue
        project.surrogates.append(
            SurrogateRef(
                id=metadata.id, name=metadata.name, model_path=_relative(model, folder)
            )
        )
