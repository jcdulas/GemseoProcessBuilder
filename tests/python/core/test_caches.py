"""The caches of the disciplines: settings, fingerprints, rules (SPEC § 8.7, § 9.1)."""

import os
import time
from pathlib import Path

import pytest
from builders import assembly
from builders import component
from builders import driver
from builders import project

from gemseo_process_builder.core.caches import CacheSetting
from gemseo_process_builder.core.caches import builds_discipline
from gemseo_process_builder.core.caches import cache_setting
from gemseo_process_builder.core.caches import cache_values
from gemseo_process_builder.core.caches import cached_nodes
from gemseo_process_builder.core.caches import default_file
from gemseo_process_builder.core.caches import fingerprint
from gemseo_process_builder.core.caches import path_of_names
from gemseo_process_builder.core.caches import read_record
from gemseo_process_builder.core.caches import record_fingerprints
from gemseo_process_builder.core.caches import record_path
from gemseo_process_builder.core.caches import write_record
from gemseo_process_builder.core.document import Document
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.quick_fixes import fix_command
from gemseo_process_builder.core.resolver import resolve
from gemseo_process_builder.core.rules import caches as cache_rules
from gemseo_process_builder.core.rules.caches import cache_problems
from gemseo_process_builder.core.validation import ValidationContext


def study(tmp_path: Path, processes: int = 1) -> Project:
    """A DOE of a sizing cached in a file, and an assembly cached in memory."""
    sizing = component("Sizing", ["x"], ["mass"])
    sizing.config = {
        "expressions": {"mass": "2*x"},
        "cache": {
            "type": "hdf5",
            "file": str(tmp_path / "study.h5"),
            "node": "Study/Sizing",
        },
    }
    other = component("Other", ["mass"], ["cost"])
    other.config = {"expressions": {"cost": "mass"}}
    group = assembly("Group", other, cache={"type": "memory"})
    doe = driver(
        "Study",
        "doe",
        sizing,
        group,
        config={"execution": {"n_processes": processes}},
    )
    return project(doe)


def test_settings_are_read_and_written_where_each_node_keeps_them(
    tmp_path: Path,
) -> None:
    model = study(tmp_path)
    sizing, group = model.root.children[0].children  # type: ignore[union-attr]
    assert cache_setting(sizing) == CacheSetting(
        type="hdf5", file=str(tmp_path / "study.h5"), node="Study/Sizing"
    )
    assert cache_setting(group) == CacheSetting(type="memory")
    assert cache_setting(group.children[0]) is None  # type: ignore[union-attr]
    memory = CacheSetting(type="memory", tolerance=1e-6)
    values = cache_values(sizing, memory)
    assert values["config"]["cache"] == {"type": "memory", "tolerance": 1e-6}
    assert values["config"]["expressions"] == {"mass": "2*x"}
    assert cache_values(sizing, None)["config"] == {"expressions": {"mass": "2*x"}}
    assert cache_values(group, None) == {"cache": {}}
    # The command of the inspector changes an assembly as a component.
    document = Document(model)
    from gemseo_process_builder.core.commands import SetNodeProperties

    document.execute(SetNodeProperties(id=group.id, values=cache_values(group, memory)))
    assert cache_setting(document.project.find(group.id)) == memory  # type: ignore[arg-type]


def test_defaults_and_where_the_script_builds_a_discipline(tmp_path: Path) -> None:
    model = study(tmp_path)
    assert path_of_names(model, "n-Sizing") == "Study/Sizing"
    assert (
        default_file(tmp_path, "Wing study!") == tmp_path / "caches" / "Wing_study_.h5"
    )
    found = {node.name: ancestors for node, ancestors, _ in cached_nodes(model)}
    assert set(found) == {"Sizing", "Group"}
    assert builds_discipline(model.root.children[0], [model.root]) is False
    inner = driver("Inner", "optimization")
    assert builds_discipline(inner, [model.root, model.root.children[0]]) is True
    hidden = assembly("Hidden", transparent=True)
    assert builds_discipline(hidden, [model.root]) is False


def test_fingerprints_change_with_the_code(tmp_path: Path) -> None:
    module = tmp_path / "wing.py"
    module.write_text("x = 1\n")
    wing = component("Wing", kind="python_class")
    wing.config = {"module_path": str(module), "class": "Wing"}
    first = fingerprint(wing, tmp_path)
    wing.config = {**wing.config, "cache": {"type": "memory"}}
    assert fingerprint(wing, tmp_path) == first  # The cache is not the code.
    later = time.time() + 10
    os.utime(module, (later, later))
    assert fingerprint(wing, tmp_path) != first
    group = assembly("Group", wing)
    before = fingerprint(group, tmp_path)
    wing.config = {**wing.config, "init_args": {"span": 2}}
    assert fingerprint(group, tmp_path) != before  # Those of its children.


def test_records_beside_the_cache_file(tmp_path: Path) -> None:
    file = tmp_path / "study.h5"
    assert read_record(file) == {}
    write_record(file, {"A": "1", "B": "2"})
    assert record_path(file).name == "study.h5.gpb.json"
    write_record(file, {"A": None})
    assert read_record(file) == {"B": "2"}
    write_record(file, {"B": None})
    assert not record_path(file).exists()
    model = study(tmp_path)
    record_fingerprints(model, tmp_path, within={"n-Other"})
    assert read_record(file) == {}
    record_fingerprints(model, tmp_path)
    assert set(read_record(file)) == {"Study/Sizing"}


def problems_of(model: Project, folder: Path) -> list[tuple[str, str]]:
    context = ValidationContext(model, resolve(model), folder=folder)
    return [(problem.code, problem.level) for problem in cache_problems(context)]


def test_a_file_cache_in_parallel_is_refused_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = study(tmp_path, processes=2)
    monkeypatch.setattr(cache_rules, "on_windows", lambda: False)
    assert problems_of(model, tmp_path) == []
    monkeypatch.setattr(cache_rules, "on_windows", lambda: True)
    context = ValidationContext(model, resolve(model), folder=tmp_path)
    (problem,) = cache_problems(context)
    assert (problem.code, problem.level, problem.node, problem.related) == (
        "cache_file_parallel",
        "error",
        "n-Sizing",
        "n-Study",
    )
    # One process for the driver.
    document = Document(model)
    document.execute(fix_command(problem, "one_process", model))  # type: ignore[arg-type]
    assert problems_of(document.project, tmp_path) == []
    # Or the cache in memory.
    model = study(tmp_path, processes=2)
    document = Document(model)
    document.execute(fix_command(problem, "cache_in_memory", model))  # type: ignore[arg-type]
    sizing = document.project.find("n-Sizing")
    assert cache_setting(sizing).type == "memory"  # type: ignore[arg-type, union-attr]
    assert problems_of(document.project, tmp_path) == []


def test_a_file_cache_without_file_and_one_out_of_date(tmp_path: Path) -> None:
    model = study(tmp_path)
    sizing = model.find("n-Sizing")
    record_fingerprints(model, tmp_path)
    assert problems_of(model, tmp_path) == []
    sizing.config = {**sizing.config, "expressions": {"mass": "3*x"}}  # type: ignore[union-attr]
    assert problems_of(model, tmp_path) == [("cache_out_of_date", "warning")]
    sizing.config = {  # type: ignore[union-attr]
        **sizing.config,  # type: ignore[union-attr]
        "cache": {"type": "hdf5", "file": "", "node": "Study/Sizing"},
    }
    assert problems_of(model, tmp_path) == [("cache_without_file", "error")]
