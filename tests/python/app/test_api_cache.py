"""The file caches in the inspector and in the data of a project (SPEC § 8.7)."""

from pathlib import Path
from typing import Any

import pytest
from golden_projects import example

from gemseo_process_builder.app.api_cache import CacheParams
from gemseo_process_builder.app.api_cache import CacheService
from gemseo_process_builder.app.api_cache import DefaultFileParams
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.core.caches import cache_setting
from gemseo_process_builder.core.caches import read_record
from gemseo_process_builder.core.caches import record_fingerprints
from gemseo_process_builder.core.caches import record_path
from gemseo_process_builder.core.model import Project


class FakeWorker:
    """Answers the cache methods; records the requests."""

    def __init__(self, entries: int) -> None:
        self.entries = entries
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def call(self, method: str, params: dict[str, Any], timeout: float) -> Any:
        self.requests.append((method, params))
        if method == "cache.clear":
            removed, self.entries = self.entries, 0
            return {"removed": removed}
        return {"exists": True, "entries": self.entries}


def cached_study(session: ProjectSession, file: Path) -> Project:
    project = example("sellar_mdf")
    sellar = project.find("n-sellar_1") or next(
        node
        for node in project.root.children[0].children  # type: ignore[union-attr]
    )
    sellar.config = {  # type: ignore[union-attr]
        **sellar.config,  # type: ignore[union-attr]
        "cache": {"type": "hdf5", "file": str(file), "node": "Optimizer/Sellar1"},
    }
    session.project = project
    return project


def test_the_inspector_counts_keeps_and_clears(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path / "data" / "untitled.gpb.json.autosave")
    file = tmp_path / "study.h5"
    project = cached_study(session, file)
    node = next(node for node in _nodes(project) if cache_setting(node))
    worker = FakeWorker(entries=3)
    service = CacheService(session, Bridge(MethodRegistry()), worker)  # type: ignore[arg-type]
    default = Path(service.default_file(DefaultFileParams())["file"])
    assert (default.parent.name, default.name) == ("caches", "Sellar_MDF.h5")
    # In the cache/ of the working folder of the study above the node (SPEC § 8.7).
    study = project.root.children[0]
    study.config = {
        **study.config,
        "execution": {"working_directory": str(tmp_path / "study")},
    }  # type: ignore[union-attr]
    assert Path(service.default_file(DefaultFileParams(id=node.id))["file"]) == (
        tmp_path / "study" / "cache" / "Sellar_MDF.h5"
    )
    assert Path(service.default_file(DefaultFileParams())["file"]) == default
    study.config = {
        key: value for key, value in study.config.items() if key != "execution"
    }  # type: ignore[union-attr]
    params = CacheParams(id=node.id)
    assert service.inspect(params) == {
        "exists": True,
        "entries": 3,
        "recorded": False,
        "differs": False,
    }
    record_fingerprints(project, session.folder)
    node.config = {**node.config, "init_args": {"changed": 1}}  # type: ignore[union-attr]
    assert service.inspect(params)["differs"]
    service.keep(params)
    assert not service.inspect(params)["differs"]
    assert service.clear(params) == {"removed": 3}
    assert read_record(file) == {}
    assert worker.requests[-1] == (
        "cache.clear",
        {"file": str(file), "node": "Optimizer/Sellar1"},
    )
    with pytest.raises(BridgeError, match="no file cache"):
        service.inspect(CacheParams(id=project.root.id))


def _nodes(project: Project) -> list[Any]:
    from gemseo_process_builder.core.model import iter_nodes

    return [node for node, _ in iter_nodes(project.root)]


def test_save_as_takes_the_default_caches_along(tmp_path: Path) -> None:
    session = ProjectSession(tmp_path / "data" / "untitled.gpb.json.autosave")
    session.project = example("sellar_mdf")
    session.save(tmp_path / "first.py")
    default = session.storage / "caches" / "first.h5"
    elsewhere = tmp_path / "mine.h5"
    for path in (default, elsewhere):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"hdf5")
    record_path(default).write_text('{"nodes": {}}', "utf-8")
    nodes = [node for node in _nodes(session.project) if node.type == "component"]
    nodes[0].config = {
        **nodes[0].config,
        "cache": {"type": "hdf5", "file": str(default), "node": "A"},
    }
    nodes[1].config = {
        **nodes[1].config,
        "cache": {"type": "hdf5", "file": str(elsewhere), "node": "B"},
    }
    old = session.storage
    session.save(tmp_path / "second.py")
    moved = session.storage / "caches" / "first.h5"
    assert cache_setting(nodes[0]).file == str(moved)  # type: ignore[union-attr]
    assert moved.is_file()
    assert record_path(moved).is_file()
    assert cache_setting(nodes[1]).file == str(elsewhere)  # type: ignore[union-attr]
    assert elsewhere.is_file()
    assert session.data_moved
    assert not (old / "caches").exists()
