"""Creation and execution of the Qt application."""

import logging
import sys

import shiboken6
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineCore import QWebEngineUrlScheme
from PySide6.QtWidgets import QApplication

from gemseo_process_builder import __version__
from gemseo_process_builder.app.api_app import register_app_methods
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.main_window import MainWindow
from gemseo_process_builder.app.scheme_handler import StaticSchemeHandler
from gemseo_process_builder.app.web_page import SCHEME_NAME
from gemseo_process_builder.app.web_page import NetworkBlocker

_LOGGER = logging.getLogger(__name__)


def register_scheme() -> None:
    """Declare the ``gpb://`` scheme to Qt WebEngine.

    This must happen before the ``QApplication`` is created.
    """
    scheme = QWebEngineUrlScheme(SCHEME_NAME.encode())
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.LocalScheme
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
        | QWebEngineUrlScheme.Flag.CorsEnabled
    )
    QWebEngineUrlScheme.registerScheme(scheme)


def create_application(argv: list[str]) -> QApplication:
    """Register the URL scheme, then create the Qt application."""
    register_scheme()
    application = QApplication(argv)
    application.setApplicationName("GEMSEO Process Builder")
    application.setApplicationVersion(__version__)
    return application


def create_profile(
    scheme_handler: StaticSchemeHandler, network_blocker: NetworkBlocker
) -> QWebEngineProfile:
    """Create the web profile of the application.

    The profile is off the record (nothing is written to disk), serves the
    ``gpb://`` scheme and blocks every network request.
    """
    profile = QWebEngineProfile()
    profile.installUrlSchemeHandler(SCHEME_NAME.encode(), scheme_handler)
    profile.setUrlRequestInterceptor(network_blocker)
    settings = profile.settings()
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
    )
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False
    )
    return profile


def run(dev_mode: bool = False) -> int:
    """Run the application until its main window is closed.

    Args:
        dev_mode: Whether to open the DevTools next to the main window.

    Returns:
        The exit code of the Qt event loop.
    """
    application = create_application(sys.argv[:1])
    scheme_handler = StaticSchemeHandler()
    network_blocker = NetworkBlocker()
    profile = create_profile(scheme_handler, network_blocker)
    registry = MethodRegistry()
    register_app_methods(registry)
    bridge = Bridge(registry, dev_mode=dev_mode)
    window = MainWindow(profile, bridge, dev_mode=dev_mode)
    window.show()
    _LOGGER.info("GEMSEO Process Builder %s started", __version__)
    exit_code = application.exec()

    # The page must be destroyed before its profile, otherwise Qt complains.
    shiboken6.delete(window)
    shiboken6.delete(profile)
    return exit_code
