"""Web page and network restrictions of the application's web view."""

import logging

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineCore import QWebEngineUrlRequestInfo
from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor

from gemseo_process_builder.app.scheme_handler import APP_HOST

_LOGGER = logging.getLogger(__name__)

SCHEME_NAME = "gpb"

BLOCKED_SCHEMES = frozenset({"http", "https", "ws", "wss", "file", "ftp"})
"""Schemes that the page must never reach: the application works offline."""

_CONSOLE_LEVELS = {
    QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel: logging.INFO,
    QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel: logging.WARNING,
    QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel: logging.ERROR,
}


def is_app_url(url: QUrl) -> bool:
    """Tell whether a URL belongs to the application (``gpb://app/...``)."""
    return url.scheme() == SCHEME_NAME and url.host() == APP_HOST


class NetworkBlocker(QWebEngineUrlRequestInterceptor):
    """Block every request leaving the application (network or local files)."""

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:  # noqa: N802
        """Block the request if its scheme is not allowed (Qt callback)."""
        url = info.requestUrl()
        if url.scheme() in BLOCKED_SCHEMES:
            _LOGGER.warning("Blocked request to %s", url.toString())
            info.block(True)


class AppWebPage(QWebEnginePage):
    """The application page: it only navigates inside ``gpb://app/``."""

    def __init__(self, profile: QWebEngineProfile) -> None:
        super().__init__(profile)

    def acceptNavigationRequest(  # noqa: N802
        self,
        url: QUrl | str,
        navigation_type: QWebEnginePage.NavigationType,
        is_main_frame: bool,
    ) -> bool:
        """Refuse any navigation outside the application (Qt callback)."""
        url = QUrl(url)
        if is_app_url(url):
            return True
        _LOGGER.warning("Blocked navigation to %s", url.toString())
        return False

    def javaScriptConsoleMessage(  # noqa: N802
        self,
        level: QWebEnginePage.JavaScriptConsoleMessageLevel,
        message: str,
        line_number: int,
        source_id: str,
    ) -> None:
        """Forward the page's console messages to Python logging (Qt callback)."""
        _LOGGER.log(
            _CONSOLE_LEVELS.get(level, logging.INFO),
            "[page] %s (%s:%d)",
            message,
            source_id,
            line_number,
        )
