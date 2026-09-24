from pathlib import Path

import pytest

from gemseo_process_builder.app.scheme_handler import STATIC_ROOT
from gemseo_process_builder.app.scheme_handler import is_safe_path
from gemseo_process_builder.app.scheme_handler import locate_static_file
from gemseo_process_builder.app.scheme_handler import mime_type_for
from gemseo_process_builder.app.scheme_handler import read_static_content


@pytest.fixture
def static_root(tmp_path: Path) -> Path:
    root = tmp_path / "static"
    (root / "js").mkdir(parents=True)
    (root / "index.html").write_text("<html></html>")
    (root / "js" / "main.js").write_text("export {};")
    (tmp_path / "secret.txt").write_text("secret")
    return root


def test_locates_a_file(static_root: Path) -> None:
    assert (
        locate_static_file("/js/main.js", static_root)
        == (static_root / "js" / "main.js").resolve()
    )


def test_missing_file_is_not_found(static_root: Path) -> None:
    assert locate_static_file("/js/missing.js", static_root) is None


def test_folder_is_not_served(static_root: Path) -> None:
    assert locate_static_file("/js", static_root) is None


@pytest.mark.parametrize(
    "url_path",
    ["/../secret.txt", "/js/../../secret.txt", "/", "", "/C:/Windows/win.ini"],
)
def test_unsafe_paths_are_rejected(static_root: Path, url_path: str) -> None:
    assert not is_safe_path(url_path)
    assert locate_static_file(url_path, static_root) is None


@pytest.mark.parametrize(
    ("url_path", "expected"),
    [
        ("/index.html", "text/html"),
        ("/js/main.js", "text/javascript"),
        ("/css/app.css", "text/css"),
        ("/icon.SVG", "image/svg+xml"),
        ("/data.bin", "application/octet-stream"),
    ],
)
def test_mime_types(url_path: str, expected: str) -> None:
    assert mime_type_for(url_path) == expected


def test_qwebchannel_is_read_from_qt_resources(static_root: Path) -> None:
    content = read_static_content("/vendor/qwebchannel.js", static_root)
    assert content is not None
    assert b"QWebChannel" in content


def test_real_static_folder_contains_the_page() -> None:
    for url_path in ("/index.html", "/js/main.js", "/vendor/d3.v7.min.js"):
        assert read_static_content(url_path, STATIC_ROOT) is not None
