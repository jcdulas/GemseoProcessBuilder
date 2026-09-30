"""The journal of a piloted run (spec § 9.1).

One JSON object per line, flushed after each record, so that the journal is
complete even when the run is stopped or fails. Records:

- ``call``: trigger, backend, model, context sent;
- ``answer``: text, decision (applied or not), refusals, token usage;
- ``segment``: index, algorithm, settings, first evaluation, reason;
- ``status``: the pilot turned off, the run finished, an error.
"""

import json
import threading
from collections.abc import Iterator
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


class Journal:
    """Appends records to a JSON-lines file; safe to use from two threads.

    Args:
        path: The file; its folder is created with the first record. ``None``
            keeps the records in memory only.
    """

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.records: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def write(self, kind: str, **fields: Any) -> dict[str, Any]:
        """Add a record and return it."""
        record = {"time": datetime.now(UTC).isoformat(), "kind": kind, **fields}
        line = json.dumps(record, default=_jsonable, ensure_ascii=False)
        with self._lock:
            self.records.append(json.loads(line))
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as file:
                    file.write(line + "\n")
        return self.records[-1]


def read_journal(path: Path) -> Iterator[dict[str, Any]]:
    """The records of a journal, skipping a last line cut by a crash."""
    with path.open(encoding="utf-8") as file:
        for line in file:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                return


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)
