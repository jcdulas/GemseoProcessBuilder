"""Rules about the caches of the disciplines (SPEC § 8.7, § 9.1)."""

import sys
from pathlib import Path

from pydantic import ValidationError

from gemseo_process_builder.core.caches import builds_discipline
from gemseo_process_builder.core.caches import cached_nodes
from gemseo_process_builder.core.caches import fingerprint
from gemseo_process_builder.core.caches import read_record
from gemseo_process_builder.core.drivers import driver_config
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.validation import Problem
from gemseo_process_builder.core.validation import ValidationContext
from gemseo_process_builder.core.validation import rule


def on_windows() -> bool:
    """Whether the runs are on Windows (patched by the tests)."""
    return sys.platform == "win32"


def _processes(driver: DriverNode) -> int:
    try:
        return driver_config(driver).execution.n_processes
    except ValidationError:
        return 1  # Reported by invalid_driver_config.


@rule("caches")
def cache_problems(context: ValidationContext) -> list[Problem]:
    """File caches without a file, in parallel on Windows, or out of date."""
    problems: list[Problem] = []
    records: dict[str, dict[str, str]] = {}
    folder = context.folder or Path.cwd()
    for node, ancestors, setting in cached_nodes(context.project):
        if setting.type != "hdf5" or not builds_discipline(node, ancestors):
            continue
        if not setting.file or not setting.node:
            problems.append(
                Problem(
                    "cache_without_file",
                    "error",
                    f"The cache of {node.name} keeps its executions in a file: "
                    "choose the file and its node.",
                    node.id,
                )
            )
            continue
        if on_windows():
            for driver in ancestors:
                if isinstance(driver, DriverNode) and _processes(driver) > 1:
                    problems.append(
                        Problem(
                            "cache_file_parallel",
                            "error",
                            f"{driver.name} runs its evaluations in "
                            f"{_processes(driver)} processes, and the cache of "
                            f"{node.name} is a file: GEMSEO does not support an "
                            "HDF5 cache in parallel on Windows. Run them in one "
                            "process, or keep the cache in memory.",
                            node.id,
                            related=driver.id,
                            quick_fixes=["one_process", "cache_in_memory"],
                        )
                    )
        if setting.file not in records:
            records[setting.file] = read_record(Path(setting.file))
        recorded = records[setting.file].get(setting.node)
        if recorded is not None and recorded != fingerprint(node, folder):
            problems.append(
                Problem(
                    "cache_out_of_date",
                    "warning",
                    f"The cache file of {node.name} holds executions of another "
                    "version of it (its code or its configuration changed since "
                    "they were computed): clear them, or keep them in the inspector.",
                    node.id,
                )
            )
    return problems
