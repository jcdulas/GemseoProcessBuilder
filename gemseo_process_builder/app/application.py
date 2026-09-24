"""Creation and execution of the Qt application."""

import logging
import sys
from pathlib import Path

import shiboken6
from PySide6.QtCore import QStandardPaths
from PySide6.QtCore import QTimer
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineCore import QWebEngineUrlScheme
from PySide6.QtWidgets import QApplication

from gemseo_process_builder import __version__
from gemseo_process_builder.app.actions import register_action_methods
from gemseo_process_builder.app.api_app import register_app_methods
from gemseo_process_builder.app.api_doc import DocController
from gemseo_process_builder.app.api_doc import QtClipboard
from gemseo_process_builder.app.api_prefs import register_prefs_methods
from gemseo_process_builder.app.api_project import ProjectController
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.dialogs import QtDialogs
from gemseo_process_builder.app.log_forwarding import LogForwarder
from gemseo_process_builder.app.log_forwarding import register_log_methods
from gemseo_process_builder.app.main_window import MainWindow
from gemseo_process_builder.app.preferences import PreferencesStore
from gemseo_process_builder.app.preferences import default_preferences_path
from gemseo_process_builder.app.project_session import AUTOSAVE_INTERVAL_MS
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.app.scheme_handler import StaticSchemeHandler
from gemseo_process_builder.app.web_page import SCHEME_NAME
from gemseo_process_builder.app.web_page import NetworkBlocker

_LOGGER = logging.getLogger(__name__)

APPLICATION_NAME = "GEMSEO Process Builder"
ORGANIZATION_NAME = "GemseoProcessBuilder"


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
    application.setApplicationName(APPLICATION_NAME)
    application.setOrganizationName(ORGANIZATION_NAME)
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


def untitled_autosave_path() -> Path:
    """Return where the autosave of a never-saved project goes."""
    folder = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(folder) / "untitled.gpb.json.autosave"


def run(
    dev_mode: bool = False,
    preferences_path: Path | None = None,
    project_path: Path | None = None,
) -> int:
    """Run the application until its main window is closed.

    Args:
        dev_mode: Whether to open the DevTools next to the main window.
        preferences_path: The preferences file; by default, the one in the
            user's configuration folder.
        project_path: A project to open at startup.

    Returns:
        The exit code of the Qt event loop.
    """
    application = create_application(sys.argv[:1])
    preferences = PreferencesStore(preferences_path or default_preferences_path())

    bridge = Bridge(MethodRegistry(), dev_mode=dev_mode)
    log_forwarder = LogForwarder(bridge)
    logging.getLogger().addHandler(log_forwarder)
    register_app_methods(bridge.registry)
    register_log_methods(bridge, log_forwarder)
    register_prefs_methods(bridge, preferences)

    scheme_handler = StaticSchemeHandler()
    network_blocker = NetworkBlocker()
    profile = create_profile(scheme_handler, network_blocker)
    window = MainWindow(profile, bridge, dev_mode=dev_mode)
    register_action_methods(bridge, window.menus)

    session = ProjectSession(
        untitled_autosave_path(), max_undo=preferences.preferences.max_undo
    )
    projects = ProjectController(session, bridge, QtDialogs(window), preferences)
    projects.register()
    DocController(session, bridge, QtClipboard()).register()
    projects.on_recent_changed(
        lambda paths: window.menus.set_recent_projects(paths, projects.open_recent)
    )
    session.on_change(lambda: window.show_project(**session.state()))
    window.show_project(**session.state())
    window.close_guard = projects.confirm_close
    autosave_timer = QTimer(window)
    autosave_timer.timeout.connect(projects.autosave)
    autosave_timer.start(AUTOSAVE_INTERVAL_MS)

    window.show()
    if project_path is not None:
        QTimer.singleShot(0, lambda: projects.open_recent(str(project_path)))
    else:
        QTimer.singleShot(0, projects.recover_untitled_at_startup)
    _LOGGER.info("%s %s started", APPLICATION_NAME, __version__)
    exit_code = application.exec()

    logging.getLogger().removeHandler(log_forwarder)
    # The page must be destroyed before its profile, otherwise Qt complains.
    shiboken6.delete(window)
    shiboken6.delete(profile)
    return exit_code
