"""The example scripts are written from their projects (tools/build_examples.py)."""

import re
from datetime import date
from pathlib import Path

import pytest
from golden_projects import EXAMPLE_PROJECTS
from golden_projects import EXAMPLES
from golden_projects import example

from gemseo_process_builder.codegen.generator import project_script

NAMES = sorted(
    path.relative_to(EXAMPLE_PROJECTS).as_posix().removesuffix(".gpb.json")
    for path in EXAMPLE_PROJECTS.rglob("*.gpb.json")
)
INCOMPLETE = {"rosenbrock_surrogate"}
"""Examples whose surrogate is built in the application: no script."""


@pytest.mark.parametrize("name", sorted(set(NAMES) - INCOMPLETE))
def test_the_example_script_is_up_to_date(name: str) -> None:
    script = EXAMPLES / f"{name}.py"
    text = script.read_text(encoding="utf-8")
    written = re.search(r" on (\d{4}-\d{2}-\d{2})\.", text)
    assert written is not None
    expected = project_script(
        example(name), script, date.fromisoformat(written.group(1))
    )
    assert text == expected, "Run python tools/build_examples.py"


def test_every_complete_example_has_a_script() -> None:
    scripts = {
        path.relative_to(EXAMPLES).as_posix().removesuffix(".py")
        for path in Path(EXAMPLES).rglob("*.py")
        if path.parent == EXAMPLES or path.stem == path.parent.name
    }
    assert scripts == set(NAMES) - INCOMPLETE
