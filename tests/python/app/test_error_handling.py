"""Uncaught errors are logged and shown without stopping the application."""

import logging
import sys
import threading

import pytest

from gemseo_process_builder.app.error_handling import ErrorReporter
from gemseo_process_builder.app.error_handling import describe
from gemseo_process_builder.app.error_handling import install_error_hooks


def failure() -> tuple[type[BaseException], BaseException, object]:
    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError as error:
        return type(error), error, error.__traceback__
    raise AssertionError


def test_description() -> None:
    kind, error, trace = failure()
    message, details = describe(kind, error, trace)  # type: ignore[arg-type]
    assert message == "ZeroDivisionError: division by zero"
    assert "Traceback" in details
    assert "1 / 0" in details


def test_errors_are_logged_and_shown(caplog: pytest.LogCaptureFixture) -> None:
    reporter = ErrorReporter()
    shown: list[str] = []
    reporter._show = lambda message, details: shown.append(message)  # type: ignore[method-assign]
    restore = install_error_hooks(reporter)
    try:
        with caplog.at_level(logging.ERROR):
            sys.excepthook(*failure())  # type: ignore[arg-type]
        assert "Unexpected error: ZeroDivisionError" in caplog.text
        assert threading.excepthook is not threading.__excepthook__
    finally:
        restore()
    assert sys.excepthook is sys.__excepthook__
