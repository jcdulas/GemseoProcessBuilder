"""Sizing folders of gemseo_nastran matched to the evaluations of a run (plan 80)."""

import json
import tempfile
from pathlib import Path
from typing import Any

from gemseo_process_builder.workers.view3d_methods import DEFAULT_STORE
from gemseo_process_builder.workers.view3d_methods import index
from gemseo_process_builder.workers.view3d_methods import match
from gemseo_process_builder.workers.view3d_methods import store_of

KEYS = {
    "crown_stringers": "fuselage.stringers.crown.count",
    "upper_side_stringers": "fuselage.stringers.upper_side.count",
}


def manifest(
    crown: int, upper: int, requested: dict[str, int] | None = None, schema: int = 1
) -> Any:
    """A manifest as gemseo_nastran writes it (abridged)."""
    stringers = {"crown": {"count": crown}, "upper_side": {"count": upper}}
    return {
        "schema": schema,
        "kind": "sizing",
        "status": "done",
        "inputs": {"family": "test_barrel", "fuselage": {"stringers": stringers}},
        "plan": {
            "requests": [
                {
                    "keys": KEYS,
                    "requested": requested
                    or {"crown_stringers": crown, "upper_side_stringers": upper},
                }
            ]
        },
        "outputs": {"mass": 320.0},
        "paths": {"model": "model.bdf"}
        if schema == 1
        else {"model": "model.bdf", "stacking": None, "envelope_environments": None},
    }


def write(store: Path, architecture: str, data: Any) -> Path:
    folder = store / "architectures" / architecture / "sizings" / "options"
    folder.mkdir(parents=True)
    text = data if isinstance(data, str) else json.dumps(data)
    (folder / "evaluation.json").write_text(text, "utf-8")
    return folder


def test_manifests_are_indexed_and_matched_to_evaluations(tmp_path: Path) -> None:
    store = tmp_path / "store"
    first = write(store, "a", manifest(4, 4))
    # A request of 5 the planner adjusted to 6: found by its requested values.
    adjusted = write(
        store, "b", manifest(6, 4, {"crown_stringers": 5, "upper_side_stringers": 4})
    )
    write(store, "c", "{not json")
    write(store, "d", {**manifest(4, 5), "schema": 3})
    running = write(store, "e", {**manifest(5, 5), "status": "running"})
    # Schema 2: the keys stacking and envelope_environments in paths.
    second = write(store, "f", manifest(6, 6, schema=2))
    sizings, problems = index(store)
    assert sorted(Path(s.folder).name for s in sizings) == ["options"] * 3
    assert len(problems) == 2  # The malformed one and the other schema.
    assert any("schema 3 is not one of [1, 2]" in problem for problem in problems)
    rows = {
        1: {"crown_stringers": 4.0, "upper_side_stringers": 4.0},
        2: {"crown_stringers": 5.0, "upper_side_stringers": 4.0},
        3: {"crown_stringers": 6.0, "upper_side_stringers": 4.0},
        4: {"crown_stringers": 5.0, "upper_side_stringers": 5.0},
        5: {"crown_stringers": 6.0, "upper_side_stringers": 6.0},
    }
    found = match(rows, sizings)
    assert found == {1: str(first), 2: str(adjusted), 3: str(adjusted), 5: str(second)}
    assert str(running) not in found.values()  # Not done: nothing to show.


def test_the_store_of_a_run(tmp_path: Path) -> None:
    def snapshot(default: str, init_args: dict[str, Any]) -> dict[str, Any]:
        sizing = {
            "type": "component",
            "config": {"module": "gemseo_nastran.sizing", "init_args": init_args},
            "ports": [
                {"local_name": "store_path", "direction": "in", "default": default}
            ],
        }
        return {"root": {"type": "assembly", "children": [sizing]}}

    assert store_of(snapshot("D:/stores/a", {})) == Path("D:/stores/a")
    assert store_of(snapshot("", {"store_path": "D:/stores/b"})) == Path("D:/stores/b")
    default = Path(tempfile.gettempdir()) / DEFAULT_STORE
    assert store_of(snapshot("", {})) == default
    assert store_of({"root": {"type": "assembly", "children": []}}) == default
