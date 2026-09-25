"""The runner process with a fake script: no GEMSEO, so it starts fast."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPOSITORY = Path(__file__).parents[3]

FAKE_SCRIPT = '''
"""A scenario-like object with the attributes the runner uses."""

import time


class Database:
    def __init__(self):
        self.listeners = []
        self.values = {}

    def add_new_iter_listener(self, listener):
        self.listeners.append(listener)

    def get_function_value(self, name, x):
        return self.values.get((name, x))

    def __len__(self):
        return len(self.values)

    def to_dataset(self):
        return self

    def to_csv(self, path):
        path.write_text("x,f")

    def to_numpy(self, dtype, na_value):
        return [[1.0, 2.0]]


class Function:
    def __init__(self, name, f_type="obj"):
        self.name = name
        self.f_type = f_type


class DesignSpace:
    def convert_array_to_dict(self, x):
        return {"x": x}


class Problem:
    def __init__(self):
        self.database = Database()
        self.objective = Function("f")
        self.constraints = [Function("g", "ineq")]
        self.observables = []
        self.design_space = DesignSpace()


class Formulation:
    def __init__(self):
        self.optimization_problem = Problem()


class Scenario:
    disciplines = []

    def __init__(self):
        self.formulation = Formulation()

    def save_optimization_history(self, path):
        path.write_text("history")

    def to_dataset(self):
        return self

    def to_csv(self, path):
        path.write_text("x,f")

    def to_numpy(self, dtype, na_value):
        return [[1.0, 2.0]]


def build_scenario():
    return Scenario()


def execute_scenario(scenario):
    print("Printed by user code.")
    database = scenario.formulation.optimization_problem.database
    for index in range(ITERATIONS):
        x = float(index)
        for listener in database.listeners:
            listener(x)
        database.values["f", x] = x * x
        database.values["g", x] = x - 2
        time.sleep(DELAY)
    if FAIL:
        raise ValueError("boom")
'''


def run_folder(tmp_path: Path, iterations: int, delay: float, fail: bool) -> Path:
    constants = f"ITERATIONS = {iterations}\nDELAY = {delay}\nFAIL = {fail}\n"
    (tmp_path / "script.py").write_text(FAKE_SCRIPT + constants, encoding="utf-8")
    mapping = {
        "kind": "scenario",
        "progress": {"unit": "iteration", "total": iterations},
    }
    (tmp_path / "script.gpb-map.json").write_text(json.dumps(mapping), encoding="utf-8")
    return tmp_path


def start(folder: Path) -> subprocess.Popen[str]:
    environment = {**os.environ, "PYTHONPATH": str(REPOSITORY), "PYTHONUTF8": "1"}
    return subprocess.Popen(
        [sys.executable, "-m", "gemseo_process_builder.runner", str(folder)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )


def finish(process: subprocess.Popen[str]) -> tuple[str, str]:
    """Read until the runner exits; its input stays open, as in the application.

    A closed input means that the application went away: the run would stop.
    """
    assert process.stdout is not None and process.stderr is not None
    output = process.stdout.read()
    errors = process.stderr.read()
    process.wait(timeout=5)
    return output, errors


def events(output: str) -> list[tuple[str, Any]]:
    messages = [json.loads(line) for line in output.splitlines() if line.strip()]
    return [(message["event"], message["payload"]) for message in messages]


def test_completed_run(tmp_path: Path) -> None:
    folder = run_folder(tmp_path, iterations=3, delay=0, fail=False)
    process = start(folder)
    output, errors = finish(process)
    received = events(output)
    names = [name for name, _ in received]
    assert names[0] == "started"
    assert names[-1] == "finished"
    finished = received[-1][1]
    assert finished["state"] == "completed"
    assert finished["summary"]["objective"] == "f"
    assert (folder / "dataset.npy").is_file()
    assert "python" in finished["versions"]
    iterations = [payload for name, payload in received if name == "iteration"]
    assert [item["index"] for item in iterations] == [1, 2, 3]
    assert iterations[2]["f"] == {"f": 4.0}
    assert iterations[2]["g"] == {"g": 0.0}
    assert iterations[2]["feasible"] is True
    assert "Printed by user code." in errors  # stdout is protected.
    assert (folder / "history.h5").read_text() == "history"
    assert (folder / "dataset.csv").exists()
    assert process.returncode == 0


def test_stop(tmp_path: Path) -> None:
    process = start(run_folder(tmp_path, iterations=1000, delay=0.01, fail=False))
    assert process.stdout is not None and process.stdin is not None
    while json.loads(process.stdout.readline())["event"] != "iteration":
        pass
    process.stdin.write('{"command": "stop"}\n')
    process.stdin.flush()
    output, _ = finish(process)
    assert events(output)[-1][1]["state"] == "stopped"
    assert (tmp_path / "history.h5").exists()  # The partial history.


def test_closed_input_stops_the_run(tmp_path: Path) -> None:
    process = start(run_folder(tmp_path, iterations=1000, delay=0.01, fail=False))
    output, _ = process.communicate(timeout=5)
    assert events(output)[-1][1]["state"] == "stopped"


def test_failure(tmp_path: Path) -> None:
    process = start(run_folder(tmp_path, iterations=1, delay=0, fail=True))
    output, _ = finish(process)
    name, payload = events(output)[-1]
    assert (name, payload["state"], payload["error"]) == (
        "finished",
        "failed",
        "ValueError: boom",
    )
    assert "Traceback" in payload["traceback"]
    assert process.returncode == 1
