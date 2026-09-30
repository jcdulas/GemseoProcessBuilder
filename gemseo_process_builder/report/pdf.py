"""Printing a report to PDF with Qt WebEngine (SPEC § 13).

The HTML report is loaded in a page that is never shown, then printed on A4
with ``QWebEnginePage.printToPdf``: the PDF looks like the report printed from
a browser, with the page breaks of its print style sheet.

Pages live in the Qt thread and print asynchronously. ``PdfPrinter.print`` is
called from another thread (a background bridge method) and waits there:
waiting in the Qt thread would stop the pages.
"""

import itertools
import threading
from pathlib import Path

from PySide6.QtCore import QMarginsF
from PySide6.QtCore import QObject
from PySide6.QtCore import QTimer
from PySide6.QtCore import QUrl
from PySide6.QtCore import Signal
from PySide6.QtCore import Slot
from PySide6.QtGui import QPageLayout
from PySide6.QtGui import QPageSize
from PySide6.QtWebEngineCore import QWebEnginePage

PRINT_TIMEOUT_S = 120.0

A4_LAYOUT = QPageLayout(
    QPageSize(QPageSize.PageSizeId.A4),
    QPageLayout.Orientation.Portrait,
    QMarginsF(14, 16, 14, 16),
    QPageLayout.Unit.Millimeter,
)


class PdfError(RuntimeError):
    """A report that could not be printed; the message is for the user."""


class _Job:
    """A PDF being printed, and what its waiting thread needs."""

    def __init__(self, html_file: Path, pdf_file: Path) -> None:
        self.html_file = html_file
        self.pdf_file = pdf_file
        self.done = threading.Event()
        self.error = ""
        self.page: QWebEnginePage | None = None


class PdfPrinter(QObject):
    """Print HTML files to PDF; create it in the Qt thread."""

    _requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._jobs: dict[int, _Job] = {}
        self._numbers = itertools.count()
        self._requested.connect(self._start)

    def print(self, html_file: Path, pdf_file: Path) -> None:
        """Print a file and wait for the PDF (not from the Qt thread).

        Raises:
            PdfError: When the page cannot be loaded or printed in time.
        """
        number = next(self._numbers)
        job = _Job(html_file, pdf_file)
        self._jobs[number] = job
        self._requested.emit(number)
        finished = job.done.wait(PRINT_TIMEOUT_S)
        self._jobs.pop(number, None)
        if not finished:
            msg = "Printing the report took too long."
            raise PdfError(msg)
        if job.error:
            raise PdfError(job.error)

    @Slot(int)
    def _start(self, number: int) -> None:
        job = self._jobs.get(number)
        if job is None:
            return
        page = QWebEnginePage(self)
        job.page = page

        def loaded(ok: bool) -> None:
            if ok:
                page.printToPdf(str(job.pdf_file), A4_LAYOUT)
            else:
                self._finish(job, f"{job.html_file.name} could not be loaded.")

        def printed(_path: str, ok: bool) -> None:
            self._finish(job, "" if ok else f"{job.pdf_file} could not be written.")

        page.loadFinished.connect(loaded)
        page.pdfPrintingFinished.connect(printed)
        page.load(QUrl.fromLocalFile(str(job.html_file)))

    def _finish(self, job: _Job, error: str) -> None:
        job.error = error
        job.done.set()
        if job.page is not None:
            # Deleted once its signals are handled.
            QTimer.singleShot(0, job.page.deleteLater)
            job.page = None
