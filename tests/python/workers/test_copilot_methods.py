"""The copilot methods of the worker, with a keyring in memory."""

import sys
from typing import Any

import keyring
import pytest
from keyring.backend import KeyringBackend

from gemseo_process_builder.workers.copilot_methods import copilot_status
from gemseo_process_builder.workers.copilot_methods import delete_key
from gemseo_process_builder.workers.copilot_methods import store_key


class MemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.passwords.pop((service, username))


@pytest.fixture
def memory_keyring(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    yield
    keyring.set_keyring(previous)


def test_the_api_key_in_the_keyring(memory_keyring: Any) -> None:
    status = copilot_status({"backend": "api_key"}, None)  # type: ignore[arg-type]
    assert (status["installed"], status["ok"]) == (True, False)
    assert status["message"].startswith("No API key")
    store_key({"key": "sk-test"}, None)  # type: ignore[arg-type]
    assert copilot_status({"backend": "api_key"}, None)["ok"]  # type: ignore[arg-type]
    delete_key({}, None)  # type: ignore[arg-type]
    assert not copilot_status({"backend": "api_key"}, None)["ok"]  # type: ignore[arg-type]


def test_without_the_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "gemseo_claude_pilot", None)
    status = copilot_status({}, None)  # type: ignore[arg-type]
    assert status["installed"] is False
    assert "pip install" in status["message"]


def test_claude_code_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    status = copilot_status({"backend": "claude_code"}, None)  # type: ignore[arg-type]
    assert status["installed"] and not status["ok"]
    assert status["message"].startswith("Claude Code is not installed")
