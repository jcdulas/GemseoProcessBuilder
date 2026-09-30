"""Unexpected errors of the UI process (SPEC § 14.2).

An exception nobody caught, in the Qt thread or in another thread, is logged
with its traceback (so it reaches the Console panel and the log file) and shown
in a dialog that does not block the application, with a "Copy details" button
for bug reports. The application keeps running.
"""

import logging
import sys
import threading
import traceback
from collections.abc import Callable
from types import TracebackType

from PySide6.QtCore import QObject
from PySide6.QtCore import Qt
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QMessageBox
from PySide6.QtWidgets import QWidget

_LOGGER = logging.getLogger(__name__)

MAX_DIALOGS = 3
"""Dialogs open at once, at most: an error repeated in a loop floods nothing."""


def describe(
    kind: type[BaseException], error: BaseException, trace: TracebackType | None
) -> tuple[str, str]:
    """The message of an error for the user, and its details for a bug report."""
    details = "".join(traceback.format_exception(kind, error, trace))
    return f"{kind.__name__}: {error}", details


class ErrorReporter(QObject):
    """Log unexpected errors and show them without blocking."""

    _reported = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__()
        self.parent_widget = parent
        self.dialogs: list[QMessageBox] = []
        # Errors of other threads are shown by the Qt thread.
        self._reported.connect(self._show, Qt.ConnectionType.QueuedConnection)

    def report(
        self,
        kind: type[BaseException],
        error: BaseException,
        trace: TracebackType | None,
    ) -> None:
        """Log an error and show it (from any thread)."""
        message, details = describe(kind, error, trace)
        _LOGGER.error("Unexpected error: %s\n%s", message, details)
        self._reported.emit(message, details)

    def _show(self, message: str, details: str) -> None:
        self.dialogs = [dialog for dialog in self.dialogs if dialog.isVisible()]
        if len(self.dialogs) >= MAX_DIALOGS:
            return
        dialog = QMessageBox(self.parent_widget)
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle("Unexpected error")
        dialog.setText(
            "An unexpected error occurred. The application keeps running; "
            "save your project to be safe."
        )
        dialog.setInformativeText(message)
        dialog.setDetailedText(details)
        copy = dialog.addButton("Copy details", QMessageBox.ButtonRole.ActionRole)
        dialog.addButton(QMessageBox.StandardButton.Close)
        # "Copy details" copies without closing the dialog.
        copy.clicked.disconnect()
        copy.clicked.connect(lambda: QApplication.clipboard().setText(details))
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()
        self.dialogs.append(dialog)


def install_error_hooks(reporter: ErrorReporter) -> Callable[[], None]:
    """Route uncaught exceptions of every thread to the reporter.

    Returns:
        A function restoring the previous hooks.
    """
    previous = sys.excepthook, threading.excepthook

    def thread_hook(arguments: threading.ExceptHookArgs) -> None:
        if arguments.exc_value is not None:
            reporter.report(
                arguments.exc_type, arguments.exc_value, arguments.exc_traceback
            )

    sys.excepthook = reporter.report
    threading.excepthook = thread_hook

    def restore() -> None:
        sys.excepthook, threading.excepthook = previous

    return restore
