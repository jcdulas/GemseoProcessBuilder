"""Writing the images exported by the page: ``image.export`` (SPEC § 13).

The page serializes the SVG of a view with its styles, and renders PNG files
itself (Chromium draws the SVG on a canvas): here, the data is only checked
and written.
"""

import base64
import binascii
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.core.atomic_write import write_bytes_atomically
from gemseo_process_builder.core.atomic_write import write_text_atomically

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ImageParams(BaseModel):
    """Parameters of ``image.export``."""

    path: str
    format: Literal["svg", "png"]
    data: str
    """The SVG document, or the PNG file encoded in base64."""


def write_image(path: Path, image_format: str, data: str) -> Path:
    """Write an exported image; the extension follows the format.

    Raises:
        ValueError: When the data is not an image of the format.
    """
    path = path.with_suffix(f".{image_format}")
    if image_format == "svg":
        if "<svg" not in data[:500]:
            msg = "The data is not an SVG document."
            raise ValueError(msg)
        write_text_atomically(path, data)
        return path
    try:
        content = base64.b64decode(data, validate=True)
    except binascii.Error:
        msg = "The data is not a base64-encoded PNG."
        raise ValueError(msg) from None
    if not content.startswith(PNG_SIGNATURE):
        msg = "The data is not a PNG image."
        raise ValueError(msg)
    write_bytes_atomically(path, content)
    return path


def register_image_methods(bridge: Bridge) -> None:
    """Register ``image.export``."""

    def export(params: ImageParams) -> str:
        try:
            return str(write_image(Path(params.path), params.format, params.data))
        except ValueError as error:
            raise BridgeError(ErrorCode.INVALID_PARAMS, str(error)) from None
        except OSError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None

    bridge.registry.add("image.export", export)
