"""The Claude copilot for the page: ``copilot.*`` methods (docs/CLAUDE_PILOT_SPEC.md).

The worker checks the backend and keeps the API key in the keyring: it runs
the interpreter of the runs. Questions on a finished run and reviews before a
run go to the copilot process (``python -m gemseo_claude_pilot.session``),
started with the interpreter and the environment of the runs; a question on a
running run goes to its runner. The journal of a run is a file of its folder,
read here. The UI process never reaches the network.
"""

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import Field

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.preferences import Preferences
from gemseo_process_builder.app.run_manager import FINAL_STATES
from gemseo_process_builder.app.run_manager import RunManager
from gemseo_process_builder.app.run_manager import copilot_environment
from gemseo_process_builder.app.worker_client import PACKAGE_PARENT
from gemseo_process_builder.app.worker_client import WorkerClient
from gemseo_process_builder.app.worker_client import WorkerRequestError
from gemseo_process_builder.app.worker_client import WorkerUnavailableError
from gemseo_process_builder.codegen.generator import CodegenError
from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.core.drivers import algorithm_name
from gemseo_process_builder.core.drivers import driver_config
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.results.store import RunStore

TIMEOUT_S = 60.0

SESSION_TIMEOUT_S = 600.0
"""Seconds a question or a review may take: Claude may read with its tools."""

SESSION_MODULE = "gemseo_claude_pilot.session"

LEFT_OUT = ("context",)
"""Fields of the journal too large for the page: the context sent to Claude."""


class StatusParams(BaseModel):
    """Parameters of ``copilot.status``."""

    backend: Literal["claude_code", "api_key"] = "claude_code"


class KeyParams(BaseModel):
    """Parameters of ``copilot.store_key``."""

    key: str = Field(min_length=1)


class JournalParams(BaseModel):
    """Parameters of ``copilot.journal``."""

    run_id: str


class AskParams(BaseModel):
    """Parameters of ``copilot.ask``."""

    run_id: str
    question: str = Field(min_length=1)


class ReviewParams(BaseModel):
    """Parameters of ``copilot.review``."""

    driver_id: str
    question: str = ""


def read_journal(store: RunStore, run_id: str) -> list[dict[str, Any]]:
    """The records of the copilot's journal of a run, without the contexts.

    Raises:
        BridgeError: When the run is unknown.
    """
    folder = store.folder_of(run_id)
    if folder is None:
        raise BridgeError(ErrorCode.NOT_FOUND, f"There is no run {run_id}.")
    path = folder / "copilot" / "journal.jsonl"
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            break  # A last line cut by a crash.
        records.append({k: v for k, v in record.items() if k not in LEFT_OUT})
    return records


def run_session(
    request: dict[str, Any],
    command: Sequence[str],
    environment: dict[str, str],
    folder: Path,
    timeout: float = SESSION_TIMEOUT_S,
) -> dict[str, Any]:
    """Run the copilot process on one request and return its answer.

    Raises:
        BridgeError: When the process fails or Claude cannot answer.
    """
    try:
        completed = subprocess.run(
            list(command),
            input=json.dumps(request),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            cwd=folder,
            env=environment,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        msg = f"The copilot did not answer: {error}"
        raise BridgeError(ErrorCode.INTERNAL, msg) from None
    lines = completed.stdout.strip().splitlines()
    try:
        answer: dict[str, Any] = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError):
        error_lines = completed.stderr.strip().splitlines()[-3:]
        raise BridgeError(
            ErrorCode.INTERNAL,
            "The copilot could not start: " + " ".join(error_lines),
        ) from None
    if not answer.get("ok"):
        raise BridgeError(ErrorCode.CONFLICT, str(answer.get("error")))
    return answer


def session_command(preferences: Preferences) -> list[str]:
    """The command of the copilot process, with the interpreter of the runs."""
    return [preferences.python_interpreter or sys.executable, "-m", SESSION_MODULE]


def session_environment(preferences: Preferences) -> dict[str, str]:
    """The environment of the copilot process: the one of the runs."""
    paths = [PACKAGE_PARENT, os.environ.get("PYTHONPATH", "")]
    return {
        **os.environ,
        **copilot_environment(preferences),
        "PYTHONPATH": os.pathsep.join(path for path in paths if path),
        "PYTHONIOENCODING": "utf-8",
    }


def register_copilot_methods(
    bridge: Bridge, worker: WorkerClient, runs: RunManager
) -> None:
    """Register the ``copilot.*`` methods."""

    def call(method: str, params: dict[str, Any]) -> Any:
        try:
            return worker.call(method, params, timeout=TIMEOUT_S)
        except WorkerRequestError as error:
            raise BridgeError(error.code, error.message) from None
        except WorkerUnavailableError as error:
            raise BridgeError(ErrorCode.WORKER_UNAVAILABLE, str(error)) from None

    def session(request: dict[str, Any], folder: Path) -> dict[str, Any]:
        preferences = runs.preferences.preferences
        return run_session(
            request,
            session_command(preferences),
            session_environment(preferences),
            folder,
        )

    def status(params: StatusParams) -> Any:
        return call("copilot.status", params.model_dump())

    def store_key(params: KeyParams) -> None:
        call("copilot.store_key", params.model_dump())

    def delete_key() -> None:
        call("copilot.delete_key", {})

    def journal(params: JournalParams) -> list[dict[str, Any]]:
        return read_journal(runs.store, params.run_id)

    def ask(params: AskParams) -> dict[str, Any]:
        """A question on a run: to its pilot while it runs, else the copilot process."""
        run = runs.runs.get(params.run_id)
        if run is not None and run.status not in FINAL_STATES:
            runs.copilot(params.run_id, "ask", {"text": params.question})
            return {"sent": True}
        folder = runs.store.folder_of(params.run_id)
        if folder is None:
            raise BridgeError(ErrorCode.NOT_FOUND, f"There is no run {params.run_id}.")
        level = runs.preferences.preferences.copilot_data_level
        request = {
            "command": "ask",
            "folder": str(folder),
            "question": params.question,
            "data_level": level,
        }
        return session(request, folder)

    def review(params: ReviewParams) -> dict[str, Any]:
        """A review of a driver before its run, from its generated script."""
        project = runs.session.project
        node = project.find(params.driver_id)
        if not isinstance(node, DriverNode) or node.kind != "optimization":
            raise BridgeError(
                ErrorCode.INVALID_PARAMS, "Choose an optimization driver."
            )
        config = driver_config(node)
        try:
            script = generate(project, node.id)
        except CodegenError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None
        preferences = runs.preferences.preferences
        level = (
            config.copilot.data_level
            if config.copilot.enabled
            else preferences.copilot_data_level
        )
        with tempfile.TemporaryDirectory(prefix="gemseo-review-") as folder:
            path = Path(folder) / "study.py"
            path.write_text(script.source, encoding="utf-8", newline="\n")
            request = {
                "command": "review",
                "script": str(path),
                "algo_name": algorithm_name(node, config),
                "settings": config.algorithm.settings,
                "budget": int(config.algorithm.settings.get("max_iter") or 100),
                "data_level": level,
                "question": params.question,
            }
            return session(request, Path(folder))

    registry = bridge.registry
    registry.add("copilot.status", status, background=True)
    registry.add("copilot.store_key", store_key, background=True)
    registry.add("copilot.delete_key", delete_key, background=True)
    registry.add("copilot.journal", journal)
    registry.add("copilot.ask", ask, background=True)
    registry.add("copilot.review", review, background=True)
