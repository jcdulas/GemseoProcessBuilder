from typing import Any

from gemseo_process_builder.runner.rate_limiter import MAX_BATCH
from gemseo_process_builder.runner.rate_limiter import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def limiter(limit: int = 2) -> tuple[RateLimiter, list[tuple[str, Any]], Clock]:
    sent: list[tuple[str, Any]] = []
    clock = Clock()
    return RateLimiter(lambda *event: sent.append(event), limit, clock), sent, clock


def test_events_beyond_the_limit_wait_for_the_next_second() -> None:
    rate, sent, clock = limiter()
    for index in range(5):
        rate.emit("iteration", index)
    assert sent == [("iteration", 0), ("iteration", 1)]
    clock.now = 1.0
    rate.emit("iteration", 5)
    assert sent[2:] == [
        ("batch", {"event": "iteration", "items": [2, 3, 4]}),
        ("iteration", 5),
    ]


def test_limits_are_per_type() -> None:
    rate, sent, _ = limiter(limit=1)
    rate.emit("log", "a")
    rate.emit("iteration", 0)
    rate.emit("log", "b")
    assert sent == [("log", "a"), ("iteration", 0)]


def test_waiting_events_with_a_key_keep_the_latest() -> None:
    rate, sent, _ = limiter(limit=1)
    rate.emit("status", {"node": "a", "state": "pending"}, key="a")
    for state in ("running", "done", "running"):
        rate.emit("status", {"node": "a", "state": state}, key="a")
    rate.emit("status", {"node": "b", "state": "done"}, key="b")
    rate.flush()
    assert sent[1] == (
        "batch",
        {
            "event": "status",
            "items": [
                {"node": "a", "state": "running"},
                {"node": "b", "state": "done"},
            ],
        },
    )


def test_batches_are_bounded_and_count_what_they_drop() -> None:
    rate, sent, _ = limiter(limit=0)
    for index in range(MAX_BATCH + 5):
        rate.emit("log", index)
    rate.flush()
    ((name, batch),) = sent
    assert name == "batch"
    assert batch["items"][0] == {"dropped": 5}
    assert batch["items"][1] == 5
    assert len(batch["items"]) == MAX_BATCH + 1


def test_flush_sends_nothing_when_nothing_waits() -> None:
    rate, sent, _ = limiter()
    rate.emit("log", "a")
    rate.flush()
    assert sent == [("log", "a")]
