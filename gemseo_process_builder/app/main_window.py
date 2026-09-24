"""The application's main window."""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QCloseEvent
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow

from gemseo_process_builder.app.web_page import AppWebPage

START_URL = QUrl("gpb://app/index.html")

MENU_TITLES = ("&File", "&Edit", "&View", "&Model", "&Run", "&Tools", "&Help")
"""Top-level menus; their content is added by later plans."""


class MainWindow(QMainWindow):
    """A window showing the web interface, with the native menu bar."""

    def __init__(self, profile: QWebEngineProfile, dev_mode: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("GEMSEO Process Builder")
        self.resize(1400, 900)

        self.web_view = QWebEngineView(self)
        self.page = AppWebPage(profile)
        self.web_view.setPage(self.page)
        self.setCentralWidget(self.web_view)

        self._create_menus()
        self._dev_tools_view: QWebEngineView | None = None
        if dev_mode:
            self._open_dev_tools()

        self.web_view.load(START_URL)

    def _create_menus(self) -> None:
        menus = {title: self.menuBar().addMenu(title) for title in MENU_TITLES}
        quit_action = menus["&File"].addAction("&Quit")
        quit_action.triggered.connect(self.close)

    def _open_dev_tools(self) -> None:
        # DevTools use the default profile, which is not restricted by the
        # network blocker of the application profile.
        self._dev_tools_view = QWebEngineView()
        self._dev_tools_view.setWindowTitle("DevTools — GEMSEO Process Builder")
        self._dev_tools_view.resize(1000, 700)
        self.page.setDevToolsPage(self._dev_tools_view.page())
        self._dev_tools_view.show()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Close the DevTools window together with the main window (Qt callback)."""
        if self._dev_tools_view is not None:
            self._dev_tools_view.close()
        super().closeEvent(event)
