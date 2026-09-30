"""Writing the images exported by the page."""

import base64
from pathlib import Path

import pytest

from gemseo_process_builder.app.image_export import PNG_SIGNATURE
from gemseo_process_builder.app.image_export import write_image

SVG = '<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>\n'


def test_svg_files_get_their_extension(tmp_path: Path) -> None:
    path = write_image(tmp_path / "canvas", "svg", SVG)
    assert path.name == "canvas.svg"
    assert path.read_text(encoding="utf-8") == SVG


def test_png_files_are_decoded(tmp_path: Path) -> None:
    png = PNG_SIGNATURE + b"rest of the image"
    path = write_image(tmp_path / "n2.png", "png", base64.b64encode(png).decode())
    assert path.read_bytes() == png


@pytest.mark.parametrize(
    ("image_format", "data", "message"),
    [
        ("svg", "<html></html>", "not an SVG"),
        ("png", "not base64!", "not a base64"),
        ("png", base64.b64encode(b"GIF89a").decode(), "not a PNG"),
    ],
)
def test_other_data_is_refused(
    tmp_path: Path, image_format: str, data: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        write_image(tmp_path / "image", image_format, data)
    assert not list(tmp_path.iterdir())
