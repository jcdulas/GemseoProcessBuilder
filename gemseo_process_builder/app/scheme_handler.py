"""Serve the web interface through the ``gpb://`` URL scheme.

The page is loaded from the package's ``static/`` folder by a
``QWebEngineUrlSchemeHandler`` running in the UI process: files are read directly
from disk, no server is started (SPEC § 3.2).
"""

import logging
from pathlib import Path
from pathlib import PurePosixPath

# Importing QtWebChannel registers the Qt resource holding qwebchannel.js.
from PySide6 import QtWebChannel  # noqa: F401
from PySide6.QtCore import QBuffer
from PySide6.QtCore import QByteArray
from PySide6.QtCore import QFile
from PySide6.QtCore import QIODevice
from PySide6.QtWebEngineCore import QWebEngineUrlRequestJob
from PySide6.QtWebEngineCore import QWebEngineUrlSchemeHandler

_LOGGER = logging.getLogger(__name__)

STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
"""The folder served under ``gpb://app/``."""

APP_HOST = "app"
"""The only host served by the scheme handler."""

QWEBCHANNEL_PATH = "vendor/qwebchannel.js"
"""The URL path under which Qt's own ``qwebchannel.js`` is served."""

QWEBCHANNEL_RESOURCE = ":/qtwebchannel/qwebchannel.js"

MIME_TYPES = {
    ".css": "text/css",
    ".html": "text/html",
    ".js": "text/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}

DEFAULT_MIME_TYPE = "application/octet-stream"


def is_safe_path(url_path: str) -> bool:
    """Tell whether a URL path can be mapped inside the static folder.

    Args:
        url_path: The path part of a ``gpb://app/...`` URL.

    Returns:
        Whether the path is relative, non-empty and free of ``..`` components.
    """
    relative = url_path.lstrip("/")
    if not relative or "\\" in relative or ":" in relative:
        return False
    return all(part not in {".", ".."} for part in PurePosixPath(relative).parts)


def locate_static_file(url_path: str, static_root: Path) -> Path | None:
    """Find the file served for a URL path.

    Args:
        url_path: The path part of a ``gpb://app/...`` URL.
        static_root: The folder served by the scheme.

    Returns:
        The file path, or ``None`` when the path is unsafe or the file does not
        exist.
    """
    if not is_safe_path(url_path):
        return None
    root = static_root.resolve()
    candidate = (root / url_path.lstrip("/")).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


def mime_type_for(url_path: str) -> str:
    """Return the MIME type of a file from its extension."""
    return MIME_TYPES.get(PurePosixPath(url_path).suffix.lower(), DEFAULT_MIME_TYPE)


def read_static_content(url_path: str, static_root: Path) -> bytes | None:
    """Read the content served for a URL path.

    ``vendor/qwebchannel.js`` is read from the Qt resources, every other path
    from the static folder.

    Args:
        url_path: The path part of a ``gpb://app/...`` URL.
        static_root: The folder served by the scheme.

    Returns:
        The content, or ``None`` when nothing is served at this path.
    """
    if url_path.lstrip("/") == QWEBCHANNEL_PATH:
        resource = QFile(QWEBCHANNEL_RESOURCE)
        if not resource.open(QIODevice.OpenModeFlag.ReadOnly):
            return None
        content = bytes(resource.readAll().data())
        resource.close()
        return content

    path = locate_static_file(url_path, static_root)
    if path is None:
        return None
    return path.read_bytes()


class StaticSchemeHandler(QWebEngineUrlSchemeHandler):
    """Answer ``gpb://app/...`` requests with the files of the static folder."""

    def __init__(self, static_root: Path = STATIC_ROOT) -> None:
        super().__init__()
        self._static_root = static_root

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:  # noqa: N802
        """Serve one request (Qt callback)."""
        url = job.requestUrl()
        url_path = url.path()
        if url.host() != APP_HOST or not is_safe_path(url_path):
            _LOGGER.warning("Rejected invalid request %s", url.toString())
            job.fail(QWebEngineUrlRequestJob.Error.UrlInvalid)
            return

        content = read_static_content(url_path, self._static_root)
        if content is None:
            _LOGGER.warning("Not found: %s", url.toString())
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return

        # The buffer is parented to the job so that it lives as long as the reply.
        buffer = QBuffer(job)
        buffer.setData(QByteArray(content))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(QByteArray(mime_type_for(url_path).encode()), buffer)
