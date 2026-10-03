"""Claude reads the values the settings of the optimizer have, defaults included."""

import json
import logging

from test_lso_pilot import EVERY_THREE
from test_lso_pilot import FINE
from test_lso_pilot import scenario

from gemseo_claude_pilot import ClaudePilot
from gemseo_claude_pilot.backends import FakeBackend

logging.getLogger("gemseo").setLevel(logging.WARNING)
logging.getLogger("gemseo_lso").setLevel(logging.WARNING)

FAST = {"dual_solver": "lbfgsb"}


def change(settings):
    return FakeBackend.decision(
        {
            "diagnosis": "d",
            "action": {"kind": "change_settings", "settings": settings},
            "rationale": "r",
        }
    )


class SetsTheDefault(FakeBackend):
    """Sets a setting to the value it already has, then to another when refused."""

    def __init__(self):
        super().__init__([], then=FINE)
        self.asked = False
        self.refusals = []
        self.contexts = []

    def send(self, request):
        last = request.messages[-1]
        if last.tool_results and any(item.is_error for item in last.tool_results):
            self.refusals.append(last.tool_results[0].content)
            return self._answer({"screening_margin": 0.4}, request)
        if not last.tool_results:
            self.contexts.append(json.loads(request.messages[0].text))
        if not self.asked and len(self.contexts) >= 2:
            self.asked = True
            return self._answer({"screening_margin": 0.3}, request)
        return super().send(request)

    def _answer(self, settings, request):
        self._then = change(settings)
        try:
            return super().send(request)
        finally:
            self._then = FINE


def test_claude_reads_the_values_of_the_settings_and_a_no_change_is_refused(tmp_path):
    backend = SetsTheDefault()
    pilot = ClaudePilot(
        mode="pilot",
        backend=backend,
        triggers=EVERY_THREE,
        journal=tmp_path / "journal.jsonl",
        threaded=False,
        report=False,
    )
    result = pilot.execute(scenario(), "LSO_MMA", max_iter=14, **FAST)
    # The context gives the value every live setting has now.
    first = backend.contexts[0]["pilot"]["settings"]
    assert first["live"]["screening_margin"] == 0.3
    assert first["live"]["move_limit"] == 0.5
    assert "max_iter" not in first["live"]  # Not a live setting.
    # Only what the engineer set differs from the defaults before Claude acts.
    assert first["live"]["dual_solver"] == "lbfgsb"
    assert first["differs_from_default"] == {"dual_solver": "auto"}
    # 0.3 is the default value: refused, with the value, and then corrected.
    assert len(backend.refusals) == 1
    assert (
        "screening_margin is already 0.3: this changes nothing" in backend.refusals[0]
    )
    (decision,) = result.decisions
    assert decision.action.settings == {"screening_margin": 0.4}
    # And the context then says what the setting was.
    after = backend.contexts[-1]["pilot"]["settings"]
    assert after["live"]["screening_margin"] == 0.4
    assert after["differs_from_default"] == {
        "dual_solver": "auto",
        "screening_margin": 0.3,
    }
