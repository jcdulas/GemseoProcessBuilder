"""The application's main window."""

from collections.abc import Callable

from PySide6.QtCore import QUrl
from PySide6.QtGui import QCloseEvent
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow

from gemseo_process_builder.app.actions import NativeMenus
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.web_page import AppWebPage

START_URL = QUrl("gpb://app/index.html")


class MainWindow(QMainWindow):
    """A window showing the web interface, with the native menu bar."""

    def __init__(
        self, profile: QWebEngineProfile, bridge: Bridge, dev_mode: bool = False
    ) -> None:
        super().__init__()
        self.setWindowTitle("GEMSEO Process Builder")
        self.resize(1400, 900)

        self.web_view = QWebEngineView(self)
        self.page = AppWebPage(profile)
        self.web_view.setPage(self.page)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject("bridge", bridge)
        self.page.setWebChannel(self.channel)
        self.setCentralWidget(self.web_view)

        self.menus = NativeMenus(self, bridge)
        self.close_guard: Callable[[], bool] | None = None
        """Called before closing; returning False keeps the window open."""

        self._dev_tools_view: QWebEngineView | None = None
        if dev_mode:
            self._open_dev_tools()

        self.web_view.load(START_URL)

    def _open_dev_tools(self) -> None:
        # DevTools use the default profile, which is not restricted by the
        # network blocker of the application profile.
        self._dev_tools_view = QWebEngineView()
        self._dev_tools_view.setWindowTitle("DevTools — GEMSEO Process Builder")
        self._dev_tools_view.resize(1000, 700)
        self.page.setDevToolsPage(self._dev_tools_view.page())
        self._dev_tools_view.show()

    def show_project(
        self, name: str, path: str | None, dirty: bool, read_only: str = ""
    ) -> None:
        """Show the project in the title bar.

        Args:
            name: The name of the project.
            path: Its file, if it has one.
            dirty: Whether it has unsaved changes.
            read_only: Who holds the project when it is read-only here.
        """
        location = f" — {path}" if path else ""
        mode = " (read-only)" if read_only else ""
        self.setWindowTitle(f"{name}{location}{mode}[*] — GEMSEO Process Builder")
        self.setWindowModified(dirty)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Ask about unsaved changes, then close the DevTools too (Qt callback)."""
        if self.close_guard is not None and not self.close_guard():
            event.ignore()
            return
        if self._dev_tools_view is not None:
            self._dev_tools_view.close()
        super().closeEvent(event)
