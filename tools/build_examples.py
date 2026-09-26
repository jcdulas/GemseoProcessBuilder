"""Write the example scripts of ``examples/`` (SPEC § 15.3).

Usage:
    python tools/build_examples.py

The examples are GEMSEO scripts that open as projects in the application. They
are written from the reference projects of ``tests/python/fixtures/examples/``
(project files of older versions); a test checks that they are up to date.
A project not complete yet, like the surrogate example whose surrogate is
built in the application, has no script.
"""

from datetime import date
from pathlib import Path

from gemseo_process_builder.codegen.generator import CodegenError
from gemseo_process_builder.codegen.generator import project_script
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.serialization import PROJECT_SUFFIX
from gemseo_process_builder.core.serialization import loads

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
REFERENCES = ROOT / "tests" / "python" / "fixtures" / "examples"


def names() -> list[str]:
    """The examples, like ``sellar_mdf`` or ``external_code/external_code``."""
    return sorted(
        path.relative_to(REFERENCES).as_posix().removesuffix(PROJECT_SUFFIX)
        for path in REFERENCES.rglob(f"*{PROJECT_SUFFIX}")
    )


def reference(name: str) -> Project:
    """The reference project of an example.

    Its relative paths lead to the files of the example, next to its script.
    """
    text = (REFERENCES / f"{name}{PROJECT_SUFFIX}").read_text(encoding="utf-8")
    return loads(text, (EXAMPLES / name).parent)


def script(name: str) -> Path:
    """The script of an example."""
    return EXAMPLES / f"{name}.py"


def main() -> None:
    for name in names():
        path = script(name)
        try:
            source = project_script(reference(name), path, date.today())
        except CodegenError as error:
            print(f"Skipped {name}: {error}")
            continue
        path.write_text(source, encoding="utf-8", newline="\n")
        print(f"Wrote {path.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
