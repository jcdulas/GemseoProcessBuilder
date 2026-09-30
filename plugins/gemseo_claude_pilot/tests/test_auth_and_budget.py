import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError
from pilot_samples import rosenbrock

from gemseo_claude_pilot import ClaudePilot
from gemseo_claude_pilot.auth import api_key
from gemseo_claude_pilot.auth import delete_api_key
from gemseo_claude_pilot.auth import store_api_key
from gemseo_claude_pilot.backends import BackendStatus
from gemseo_claude_pilot.backends import FakeBackend
from gemseo_claude_pilot.backends import Usage
from gemseo_claude_pilot.backends import create_backend
from gemseo_claude_pilot.backends.api import ApiKeyBackend
from gemseo_claude_pilot.backends.claude_code import ClaudeCodeBackend
from gemseo_claude_pilot.budget import Budget
from gemseo_claude_pilot.triggers import TriggerSettings


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.passwords = {}

    def get_password(self, service, username):
        return self.passwords.get((service, username))

    def set_password(self, service, username, password):
        self.passwords[(service, username)] = password

    def delete_password(self, service, username):
        if self.passwords.pop((service, username), None) is None:
            raise PasswordDeleteError(username)


@pytest.fixture
def memory_keyring(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    yield
    keyring.set_keyring(previous)


def test_api_key_from_the_keyring(memory_keyring, monkeypatch):
    assert api_key() is None
    store_api_key(" sk-stored \n")
    assert api_key() == "sk-stored"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-environment")
    assert api_key() == "sk-environment"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    delete_api_key()
    delete_api_key()  # Nothing to delete: no error.
    assert api_key() is None


def test_create_backend(monkeypatch):
    assert isinstance(create_backend("claude_code"), ClaudeCodeBackend)
    assert isinstance(create_backend("api_key"), ApiKeyBackend)
    assert create_backend("off") is None
    with pytest.raises(ValueError, match="Unknown backend 'magic'"):
        create_backend("magic")
    monkeypatch.delenv("GEMSEO_CLAUDE_PILOT_BACKEND")
    assert isinstance(create_backend(), ClaudeCodeBackend)
    monkeypatch.setenv("GEMSEO_CLAUDE_PILOT_BACKEND", "api_key")
    assert isinstance(create_backend(), ApiKeyBackend)


def test_budget():
    budget = Budget(max_calls=3, max_tokens=1000, max_cost_usd=0.5)
    assert budget.spent(2, Usage(400, 100)) == ""
    assert budget.spent(3, Usage()) == "the 3 calls of the budget are made"
    assert (
        budget.spent(0, Usage(900, 100)) == "the 1,000 tokens of the budget are spent"
    )
    assert budget.spent(0, Usage(cost_usd=0.5)) == "the $0.5 of the budget are spent"


def test_the_pilot_stops_asking_when_the_budget_is_spent():
    pilot = ClaudePilot(
        mode="observer",
        backend=FakeBackend([], then=FakeBackend.decision({"diagnosis": "Fine."})),
        triggers=TriggerSettings(period=2, min_interval=0, check_every=1, start=False),
        journal=False,
        threaded=False,
        budget=Budget(max_calls=2),
    )
    pilot.execute(rosenbrock(), "SLSQP", max_iter=20)
    kinds = [record["kind"] for record in pilot.journal.records]
    assert kinds.count("call") == 2
    budget = [r for r in pilot.journal.records if r.get("state") == "budget"]
    assert len(budget) == 1


class UnavailableBackend(FakeBackend):
    def check(self):
        return BackendStatus(False, "Claude Code is not logged in.")


def test_an_unavailable_backend_leaves_the_run_as_is():
    scenario = rosenbrock()
    result = ClaudePilot(
        mode="pilot", backend=UnavailableBackend([]), journal=False
    ).execute(scenario, "SLSQP", max_iter=10)
    assert result.stop_reason == "no backend"
    assert result.disabled == "Claude Code is not logged in."
    assert len(scenario.formulation.optimization_problem.database) == 10
