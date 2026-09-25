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
from gemseo_process_builder.app.api_algorithms import AlgorithmService
from gemseo_process_builder.app.api_app import register_app_methods
from gemseo_process_builder.app.api_codegen import CodegenController
from gemseo_process_builder.app.api_codegen import qt_ask_script_path
from gemseo_process_builder.app.api_derivatives import DerivativesService
from gemseo_process_builder.app.api_doc import DocController
from gemseo_process_builder.app.api_doc import QtClipboard
from gemseo_process_builder.app.api_drivers import DriverService
from gemseo_process_builder.app.api_executable import ExecutableController
from gemseo_process_builder.app.api_n2 import register_n2_methods
from gemseo_process_builder.app.api_postproc import PostprocController
from gemseo_process_builder.app.api_prefs import register_prefs_methods
from gemseo_process_builder.app.api_project import ProjectController
from gemseo_process_builder.app.api_report import ReportController
from gemseo_process_builder.app.api_resolve import ResolutionService
from gemseo_process_builder.app.api_results import ResultsController
from gemseo_process_builder.app.api_run import register_run_methods
from gemseo_process_builder.app.api_surrogates import SurrogateController
from gemseo_process_builder.app.api_worker import register_worker_methods
from gemseo_process_builder.app.api_xdsm import XdsmController
from gemseo_process_builder.app.benchmark_mode import UnattendedDialogs
from gemseo_process_builder.app.benchmark_mode import register_benchmark_methods
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.catalog_service import CatalogCache
from gemseo_process_builder.app.catalog_service import CatalogService
from gemseo_process_builder.app.component_service import ComponentService
from gemseo_process_builder.app.dialogs import Dialogs
from gemseo_process_builder.app.dialogs import QtDialogs
from gemseo_process_builder.app.dialogs import register_dialog_methods
from gemseo_process_builder.app.error_handling import ErrorReporter
from gemseo_process_builder.app.error_handling import install_error_hooks
from gemseo_process_builder.app.image_export import register_image_methods
from gemseo_process_builder.app.log_forwarding import LogForwarder
from gemseo_process_builder.app.log_forwarding import register_log_methods
from gemseo_process_builder.app.main_window import MainWindow
from gemseo_process_builder.app.preferences import Preferences
from gemseo_process_builder.app.preferences import PreferencesStore
from gemseo_process_builder.app.preferences import default_preferences_path
from gemseo_process_builder.app.project_session import AUTOSAVE_INTERVAL_MS
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.app.run_manager import RunManager
from gemseo_process_builder.app.scheme_handler import StaticSchemeHandler
from gemseo_process_builder.app.validation_service import ValidationService
from gemseo_process_builder.app.web_page import SCHEME_NAME
from gemseo_process_builder.app.web_page import NetworkBlocker
from gemseo_process_builder.app.worker_client import WorkerClient

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
    benchmark: str | None = None,
    benchmark_output: Path | None = None,
) -> int:
    """Run the application until its main window is closed.

    Args:
        dev_mode: Whether to open the DevTools next to the main window.
        preferences_path: The preferences file; by default, the one in the
            user's configuration folder.
        project_path: A project to open at startup.
        benchmark: A benchmark scenario to run on the project, then quit.
        benchmark_output: The file receiving the measurements of the benchmark.

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
    restore_error_hooks = install_error_hooks(ErrorReporter(window))
    register_action_methods(bridge, window.menus)
    bridge.registry.add("app.openDevTools", window.open_dev_tools)

    session = ProjectSession(
        untitled_autosave_path(), max_undo=preferences.preferences.max_undo
    )
    # A benchmark never waits for the user.
    dialogs: Dialogs = QtDialogs(window) if benchmark is None else UnattendedDialogs()
    projects = ProjectController(session, bridge, dialogs, preferences)
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

    worker = WorkerClient(interpreter=preferences.preferences.python_interpreter)
    register_worker_methods(bridge, worker)

    def interpreter_changed(old: Preferences, new: Preferences) -> None:
        if old.python_interpreter != new.python_interpreter:
            worker.interpreter = new.python_interpreter
            worker.restart()

    preferences.on_change(interpreter_changed)

    cache_folder = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation
    )
    catalog = CatalogService(
        bridge,
        worker,
        preferences,
        session,
        CatalogCache(Path(cache_folder) / "catalog_cache.json"),
    )
    catalog.register()
    components = ComponentService(session, bridge, worker)
    components.register()
    resolution = ResolutionService(session, bridge)
    resolution.register()
    register_n2_methods(bridge, resolution)
    algorithms = AlgorithmService(bridge, worker)
    algorithms.register()
    DriverService(session, bridge, resolution, algorithms).register()
    validation = ValidationService(
        session, bridge, resolution, components, preferences, algorithms, worker
    )
    validation.register()
    DerivativesService(session, bridge, worker).register()
    runs = RunManager(session, bridge, worker, preferences, validation.run)
    register_run_methods(bridge, runs)
    ResultsController(runs.store, bridge, worker).register()
    PostprocController(runs.store, bridge, worker).register()
    SurrogateController(session, runs.store, bridge, worker).register()
    ReportController(session, runs.store, bridge).register()
    XdsmController(session, bridge, worker).register()
    ExecutableController(session, bridge, worker).register()
    scheme_handler.run_folder = runs.store.folder_of
    register_dialog_methods(bridge, window)
    register_image_methods(bridge)
    CodegenController(session, bridge, qt_ask_script_path(window)).register()

    if benchmark is not None and project_path is not None:
        register_benchmark_methods(
            bridge,
            benchmark,
            project_path,
            benchmark_output or Path("benchmark.json"),
            application.quit,
        )
    else:
        bridge.registry.add("benchmark.scenario", lambda: None)

    window.show()
    QTimer.singleShot(0, worker.start)
    # In benchmark mode, the page opens the project itself, measuring it.
    if project_path is None:
        QTimer.singleShot(0, projects.recover_untitled_at_startup)
    elif benchmark is None:
        QTimer.singleShot(0, lambda: projects.open_recent(str(project_path)))
    _LOGGER.info("%s %s started", APPLICATION_NAME, __version__)
    exit_code = application.exec()
    session.release_lock()
    restore_error_hooks()

    runs.stop_all()
    worker.stop()
    logging.getLogger().removeHandler(log_forwarder)
    # The page must be destroyed before its profile, otherwise Qt complains.
    shiboken6.delete(window)
    shiboken6.delete(profile)
    return exit_code
