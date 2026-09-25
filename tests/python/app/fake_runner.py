"""A fake runner: ``python fake_runner.py <mode> <run folder>``."""

import json
import sys
import time


def send(event: str, payload: object = None) -> None:
    sys.stdout.write(json.dumps({"event": event, "payload": payload}) + "\n")
    sys.stdout.flush()


mode = sys.argv[1]
send("started", {"run_id": "fake", "pid": 0})
if mode == "complete":
    send("log", {"level": "INFO", "message": "Hello from the run.", "logger": "x"})
    send("iteration", {"index": 1})
    send(
        "finished",
        {
            "state": "completed",
            "summary": {"n_evaluations": 1, "objective": "f", "best_objective": 1.0},
            "variables": [{"name": "x", "role": "design variable"}],
            "versions": {"python": "3.12"},
        },
    )
elif mode == "stop":
    for line in sys.stdin:
        if "stop" in line:
            send("finished", {"state": "stopped", "summary": {}})
            break
elif mode == "hang":
    time.sleep(30)
elif mode == "crash":
    sys.exit(3)
