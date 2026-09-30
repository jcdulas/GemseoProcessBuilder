from pathlib import Path

import pytest

from gemseo_process_builder.app.scheme_handler import StaticSchemeHandler
from gemseo_process_builder.app.scheme_handler import locate_run_file


@pytest.fixture
def runs(tmp_path: Path) -> dict[str, Path]:
    """Two runs of the open project, and one of another project."""
    folders = {}
    for project, run_id in (("open", "r-1"), ("open", "r-2"), ("other", "r-9")):
        folder = tmp_path / f"{project}.runs" / run_id
        (folder / "postproc" / "OptHistoryView-1").mkdir(parents=True)
        (folder / "postproc" / "OptHistoryView-1" / "objective.svg").write_text(
            "<svg/>"
        )
        folders[run_id] = folder
    (tmp_path / "open.runs" / "secret.txt").write_text("secret")
    return folders


def resolver(runs: dict[str, Path]):  # type: ignore[no-untyped-def]
    open_runs = {"r-1": runs["r-1"], "r-2": runs["r-2"]}
    return open_runs.get


def test_serves_a_file_of_a_run(runs: dict[str, Path]) -> None:
    path = locate_run_file(
        "/r-1/postproc/OptHistoryView-1/objective.svg", resolver(runs)
    )
    assert (
        path
        == (runs["r-1"] / "postproc" / "OptHistoryView-1" / "objective.svg").resolve()
    )


@pytest.mark.parametrize(
    "url_path",
    [
        "/r-1/../secret.txt",
        "/r-1/../r-2/postproc/OptHistoryView-1/objective.svg",
        "/r-1/postproc",
        "/r-1/",
        "/r-1",
        "/r-1/C:/Windows/win.ini",
        "/r-1/postproc/missing.svg",
    ],
)
def test_rejects_paths_outside_the_run(runs: dict[str, Path], url_path: str) -> None:
    assert locate_run_file(url_path, resolver(runs)) is None


def test_rejects_runs_of_another_project(runs: dict[str, Path]) -> None:
    assert (
        locate_run_file("/r-9/postproc/OptHistoryView-1/objective.svg", resolver(runs))
        is None
    )


def test_handler_serves_run_files_once_it_knows_the_runs(runs: dict[str, Path]) -> None:
    handler = StaticSchemeHandler()
    url_path = "/r-1/postproc/OptHistoryView-1/objective.svg"
    assert handler.read("run", url_path) is None
    handler.run_folder = resolver(runs)
    assert handler.read("run", url_path) == b"<svg/>"
    assert handler.read("other", url_path) is None
