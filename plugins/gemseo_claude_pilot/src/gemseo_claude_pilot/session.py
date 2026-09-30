"""The copilot process: questions on a finished run, reviews before a run (spec § 3).

``python -m gemseo_claude_pilot.session`` reads one JSON request on its input
and writes one JSON answer on its output, then exits. GEMSEO Process Builder
runs it with the interpreter and the environment of the runs, so that the UI
process never reaches the network.

Requests:

- ``{"command": "ask", "folder": ..., "question": ..., "data_level": ...}``:
  a question on a finished run, answered from its ``history.h5`` and the
  journal of its copilot; the question and the answer go to the journal;
- ``{"command": "review", "script": ..., "algo_name": ..., "settings": ...,
  "budget": ..., "data_level": ...}``: a review of a study before its run,
  from its script, whose ``build_scenario()`` builds the scenario without
  running it.

Answer: ``{"ok": true, "text": ..., "usage": {...}}`` or ``{"ok": false,
"error": ...}``. Claude only reads: after or before a run, nothing is decided.
"""

import importlib.util
import json
import sys
import uuid
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any
from typing import TextIO

from gemseo_claude_pilot.advisor import Models
from gemseo_claude_pilot.backends import create_backend
from gemseo_claude_pilot.backends.base import Backend
from gemseo_claude_pilot.backends.base import LoopingBackend
from gemseo_claude_pilot.context import PastDecision
from gemseo_claude_pilot.context import TriggerKind
from gemseo_claude_pilot.context import build_context
from gemseo_claude_pilot.context import render
from gemseo_claude_pilot.decisions import Decision
from gemseo_claude_pilot.exchange import exchange
from gemseo_claude_pilot.guardrails import Checked
from gemseo_claude_pilot.guardrails import RejectedDecisionError
from gemseo_claude_pilot.journal import Journal
from gemseo_claude_pilot.journal import read_journal
from gemseo_claude_pilot.privacy import Anonymizer
from gemseo_claude_pilot.privacy import DataLevel
from gemseo_claude_pilot.prompts import system_prompt
from gemseo_claude_pilot.snapshots import Entry
from gemseo_claude_pilot.snapshots import ProblemSnapshot
from gemseo_claude_pilot.snapshots import components_of
from gemseo_claude_pilot.snapshots import database_entries
from gemseo_claude_pilot.snapshots import history_from_entries
from gemseo_claude_pilot.snapshots import snapshot_problem
from gemseo_claude_pilot.tools import READ_TOOLS
from gemseo_claude_pilot.tools import ToolAnswers

REVIEW = (
    "Review this optimization before it runs: is the problem well posed (bounds, "
    "scaling, starting point, constraints), do the algorithm and its settings "
    "suit it, and is the budget enough? Say what to change, if anything."
)

AnyBackend = Backend | LoopingBackend


class SessionError(Exception):
    """A request that cannot be answered; the message is for the user."""


def ask(
    folder: Path,
    question: str,
    data_level: DataLevel = "no_code",
    backend: AnyBackend | None = None,
) -> dict[str, Any]:
    """Answer a question on a finished run.

    Args:
        folder: The run folder.
        question: The question of the user.
        data_level: What may be sent, when the run had no copilot; a piloted
            run keeps its own.
        backend: The way to Claude; the one of the environment by default.
    """
    from gemseo.algos.optimization_problem import OptimizationProblem

    history_file = folder / "history.h5"
    if not history_file.is_file():
        msg = "The run has no history to talk about."
        raise SessionError(msg)
    journal_path = folder / "copilot" / "journal.jsonl"
    records = list(read_journal(journal_path)) if journal_path.is_file() else []
    started = next(
        (r for r in records if r["kind"] == "status" and r.get("state") == "started"),
        {},
    )
    problem = OptimizationProblem.from_hdf(history_file)
    entries = database_entries(problem)
    snapshot = snapshot_problem(
        problem,
        started.get("algo_name") or _run_algorithm(folder),
        int(started.get("budget") or len(entries) or 1),
        started.get("settings") or {},
    )
    decisions = [
        PastDecision(0, Decision.model_validate(record["decision"]))
        for record in records
        if record["kind"] == "decision"
    ]
    journal = Journal(journal_path)
    journal.write("user", command="ask", params={"text": question})
    return _talk(
        backend,
        snapshot,
        entries,
        "question",
        question,
        started.get("data_level") or data_level,
        journal,
        decisions,
    )


def review(
    script: Path,
    algo_name: str,
    settings: Mapping[str, Any],
    budget: int,
    data_level: DataLevel = "no_code",
    question: str = "",
    backend: AnyBackend | None = None,
) -> dict[str, Any]:
    """Review a study before its run, from its script.

    Args:
        script: The script; its ``build_scenario()`` builds the scenario.
        algo_name: The algorithm the study will run.
        settings: Its settings.
        budget: The evaluations it may spend.
        data_level: What may be sent.
        question: What the user asks; a general review by default.
        backend: The way to Claude; the one of the environment by default.
    """
    scenario = _build_scenario(script)
    problem = scenario.formulation.optimization_problem
    snapshot = snapshot_problem(
        problem,
        algo_name,
        budget,
        settings,
        formulation=type(scenario.formulation).__name__,
        components=components_of(scenario, data_level == "full"),
    )
    return _talk(backend, snapshot, [], "start", question or REVIEW, data_level)


def _talk(
    backend: AnyBackend | None,
    snapshot: ProblemSnapshot,
    entries: list[Entry],
    trigger: TriggerKind,
    question: str,
    data_level: DataLevel,
    journal: Journal | None = None,
    decisions: list[PastDecision] | None = None,
) -> dict[str, Any]:
    """Ask Claude, with the read tools only, and return its answer in words."""
    backend = backend or create_backend()
    if backend is None:
        msg = "The copilot is off: choose a way to reach Claude in the preferences."
        raise SessionError(msg)
    status = getattr(backend, "check", lambda: None)()
    if status is not None and not status.ok:
        raise SessionError(status.message)
    history = history_from_entries(entries, snapshot)
    anonymizer = Anonymizer(snapshot) if data_level == "anonymized" else None
    context = render(
        build_context(
            snapshot,
            history,
            trigger=trigger,
            decisions=decisions or [],
            question=question,
            level=data_level,
            anonymizer=anonymizer,
            pilot={"mode": "after the run" if entries else "before the run"},
        )
    )
    models = Models()
    model = models.decision
    if journal is not None:
        journal.write(
            "call",
            trigger=trigger,
            backend=backend.name,
            model=model,
            context=context,
            question=question,
        )
    result = exchange(
        backend,
        system_prompt(),
        model,
        context,
        _no_decision,
        answer_tool=ToolAnswers(snapshot, history, entries, data_level, anonymizer),
        tools=READ_TOOLS,
        effort=models.effort_of(model),
    )
    text = result.text if anonymizer is None else anonymizer.reveal(result.text)
    if journal is not None:
        journal.write(
            "answer", trigger=trigger, text=text, usage=result.usage, question=question
        )
    return {"ok": True, "text": text, "usage": asdict(result.usage)}


def _no_decision(decision: Decision) -> Checked:
    raise RejectedDecisionError(["no decision now: answer in words"])


def _run_algorithm(folder: Path) -> str:
    """The algorithm of a run, from its ``run.json``."""
    try:
        info = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(info.get("algorithm") or "")


def _build_scenario(script: Path) -> Any:
    """The scenario of a script, built but not run."""
    name = f"gemseo_claude_pilot_review_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        msg = f"{script} cannot be read."
        raise SessionError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(script.parent))
    spec.loader.exec_module(module)
    if not hasattr(module, "build_scenario"):
        msg = f"{script.name} has no build_scenario() function."
        raise SessionError(msg)
    return module.build_scenario()


def handle(request: Mapping[str, Any]) -> dict[str, Any]:
    """Answer one request."""
    command = request.get("command")
    level: DataLevel = request.get("data_level") or "no_code"
    if command == "ask":
        return ask(Path(request["folder"]), str(request["question"]), level)
    if command == "review":
        return review(
            Path(request["script"]),
            str(request["algo_name"]),
            request.get("settings") or {},
            int(request.get("budget") or 100),
            level,
            str(request.get("question") or ""),
        )
    msg = f"Unknown command {command!r}."
    raise SessionError(msg)


def main(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Read one request, write its answer; user code prints go to the error stream."""
    stdin = stdin or sys.stdin
    output = stdout or sys.stdout
    previous, sys.stdout = sys.stdout, sys.stderr  # Prints of the user's code.
    try:
        answer = handle(json.loads(stdin.read()))
    except Exception as error:  # Every failure is an answer for the user.
        answer = {"ok": False, "error": f"{error}"}
    finally:
        sys.stdout = previous
    output.write(json.dumps(answer, ensure_ascii=False) + "\n")
    output.flush()
    return 0 if answer["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
