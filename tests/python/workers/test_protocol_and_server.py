import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from gemseo_process_builder.workers.introspection import build_server
from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.protocol import decode
from gemseo_process_builder.workers.protocol import encode
from gemseo_process_builder.workers.server import RequestContext
from gemseo_process_builder.workers.server import WorkerError
from gemseo_process_builder.workers.server import WorkerServer

ROOT = Path(__file__).resolve().parents[3]


def test_encode_decode_round_trip() -> None:
    message = {"id": "1", "result": {"a": [1, 2]}, "text": "é"}
    assert decode(encode(message)) == message


def test_encode_numpy_and_sets() -> None:
    assert json.loads(encode({"v": np.array([1.5, 2.0]), "s": {3}})) == {
        "v": [1.5, 2.0],
        "s": [3],
    }


@pytest.mark.parametrize("line", ["", "  ", "not json", "[1, 2]"])
def test_decode_ignores_bad_lines(line: str) -> None:
    assert decode(line) is None


def test_channel_writes_lines() -> None:
    stream = io.StringIO()
    channel = EventChannel(stream)
    channel.event("ready", {"x": 1})
    assert stream.getvalue() == '{"event": "ready", "payload": {"x": 1}}\n'


def test_channel_protects_stdout_in_a_subprocess() -> None:
    code = (
        "from gemseo_process_builder.workers.protocol import EventChannel\n"
        "channel = EventChannel()\n"
        "print('noise')\n"
        "channel.event('done', 1)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=5,
        check=True,
    )
    assert [decode(line) for line in result.stdout.splitlines()] == [
        {"event": "done", "payload": 1}
    ]
    assert "noise" in result.stderr


@pytest.fixture
def server() -> WorkerServer:
    server = WorkerServer(EventChannel(io.StringIO()))

    def add(params: dict[str, Any], context: RequestContext) -> int:
        return int(params["a"]) + int(params["b"])

    def fail(params: dict[str, Any], context: RequestContext) -> None:
        raise ValueError("boom")

    def refuse(params: dict[str, Any], context: RequestContext) -> None:
        raise WorkerError("not_found", "Nothing here.", {"x": 1})

    server.add("add", add)
    server.add("fail", fail)
    server.add("refuse", refuse)
    return server


def test_dispatch(server: WorkerServer) -> None:
    response = server.handle({"id": "1", "method": "add", "params": {"a": 1, "b": 2}})
    assert response == {"id": "1", "ok": True, "result": 3}


def test_unknown_method(server: WorkerServer) -> None:
    assert server.handle({"id": "2", "method": "nope"})["error"]["code"] == (
        "unknown_method"
    )


def test_malformed_request(server: WorkerServer) -> None:
    assert server.handle({"id": "3", "params": []})["error"]["code"] == (
        "invalid_request"
    )


def test_exceptions_become_internal_errors(server: WorkerServer) -> None:
    error = server.handle({"id": "4", "method": "fail"})["error"]
    assert error["code"] == "internal"
    assert error["message"] == "boom"
    assert "ValueError" in "".join(error["details"])


def test_worker_errors_keep_their_code(server: WorkerServer) -> None:
    error = server.handle({"id": "5", "method": "refuse"})["error"]
    assert (error["code"], error["details"]) == ("not_found", {"x": 1})


def test_cancelled_before_running(server: WorkerServer) -> None:
    server.context_for("6")
    server.cancel("6")
    assert server.handle({"id": "6", "method": "add", "params": {"a": 1, "b": 1}})[
        "error"
    ]["code"] == ("cancelled")


def test_serve_reads_until_end_of_input(server: WorkerServer) -> None:
    output = io.StringIO()
    server.channel = EventChannel(output)
    lines = [
        encode({"id": "a", "method": "add", "params": {"a": 1, "b": 1}}),
        "garbage",
        encode({"id": "b", "method": "add", "params": {"a": 2, "b": 2}}),
    ]
    server.serve(io.StringIO("\n".join(lines) + "\n"))
    results = [decode(line) for line in output.getvalue().splitlines()]
    assert [(r["id"], r["result"]) for r in results if r] == [("a", 2), ("b", 4)]


def test_builtin_methods() -> None:
    server = build_server(EventChannel(io.StringIO()))
    assert server.handle({"id": "1", "method": "worker.ping"})["result"] == "pong"
    versions = server.handle({"id": "2", "method": "worker.versions"})["result"]
    assert versions["python"].startswith("3.")
    assert server.handle(
        {"id": "3", "method": "worker.sleep", "params": {"seconds": 0.02}}
    )["ok"]
