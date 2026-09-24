import os
import time
from pathlib import Path

from gemseo_process_builder.app.catalog_service import CatalogCache
from gemseo_process_builder.catalog.models import FileScan
from gemseo_process_builder.catalog.scanner import catalog_files
from gemseo_process_builder.catalog.scanner import scan_file

FIXTURES = Path(__file__).parent / "fixtures"


def test_catalog_files_skip_caches() -> None:
    names = [path.relative_to(FIXTURES).as_posix() for path in catalog_files(FIXTURES)]
    assert names == [
        "disciplines.py",
        "helpers.py",
        "sub/broken.py",
        "sub/solver.gpbwrap.json",
    ]


def test_defined_classes_and_decorated_functions() -> None:
    scan = scan_file(FIXTURES / "disciplines.py")
    assert scan.error is None
    entries = {entry.name: entry for entry in scan.entries}
    assert set(entries) == {"Wing", "lift"}
    assert entries["Wing"].kind == "python_class"
    assert entries["Wing"].description == "Compute the lift of a wing."
    assert entries["lift"].kind == "python_function"
    assert entries["lift"].metadata["units"] == {"area": "m**2", "lift": "N"}
    assert entries["lift"].description == "Lift of a wing"


def test_import_errors_are_reported() -> None:
    scan = scan_file(FIXTURES / "sub" / "broken.py")
    assert scan.entries == []
    assert scan.error is not None
    assert "RuntimeError: this module cannot be imported" in scan.error.message
    assert "Traceback" in scan.error.traceback


def test_descriptors() -> None:
    scan = scan_file(FIXTURES / "sub" / "solver.gpbwrap.json")
    assert [(e.kind, e.name) for e in scan.entries] == [("executable", "solver")]


def test_cache_detects_changes_and_deletions(tmp_path: Path) -> None:
    first, second = tmp_path / "a.py", tmp_path / "b.py"
    first.write_text("")
    second.write_text("")
    cache = CatalogCache(tmp_path / "cache.json")
    assert cache.outdated([first, second]) == [first, second]
    cache.update(
        [FileScan(path=str(p), mtime=p.stat().st_mtime) for p in (first, second)],
        [first, second],
    )
    cache.save()
    reloaded = CatalogCache(tmp_path / "cache.json")
    assert reloaded.outdated([first, second]) == []
    assert reloaded.outdated([first, second], force=True) == [first, second]
    later = time.time() + 10
    os.utime(first, (later, later))
    assert reloaded.outdated([first, second]) == [first]
    reloaded.update([], [second])
    assert list(reloaded.scans) == [str(second)]


def test_invalid_cache_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    path.write_text("[not a cache")
    assert CatalogCache(path).scans == {}
