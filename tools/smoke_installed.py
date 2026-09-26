"""Run every example project with the installed package (release checklist).

Usage:
    python tools/smoke_installed.py

For each example (its project, see ``tools/build_examples.py``): check it (no
validation error), generate the script of its study and run it, then compare
the result with the expected one.
The surrogate example is chained: its DOE runs, a surrogate is trained on it,
and the optimizer runs on the surrogate.

Run it from outside the repository with the interpreter of a fresh virtual
environment, so that the installed package is tested and not the sources:

    cd /tmp && /tmp/gpb/bin/python /path/to/tools/smoke_installed.py
"""

import importlib.util
import io
import math
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import gemseo_process_builder
from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.core.demos import demos_folder
from gemseo_process_builder.core.demos import find_demos
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.resolver import resolve
from gemseo_process_builder.core.validation import ValidationContext
from gemseo_process_builder.core.validation import validate
from gemseo_process_builder.results.models import RunInfo
from gemseo_process_builder.results.models import VariableInfo
from gemseo_process_builder.results.models import write_info
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.surrogate_methods import train

# The folder of this file comes first in sys.path when it runs.
from build_examples import reference  # isort: skip


def load_script(project: Project, target: str, folder: Path) -> Any:
    """Generate the script of a node and import it."""
    script = generate(project, target)
    path = folder / f"{target}.py"
    path.write_text(script.source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(f"smoke_{target}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_study(project: Project, target: str, folder: Path) -> Any:
    """Generate the script of a study, run it, and return its scenario."""
    module = load_script(project, target, folder)
    scenario = module.build_scenario()
    module.execute_scenario(scenario)
    return scenario


def process_output(target: str, output: str, ok: Callable[[float], bool]) -> "Check":
    """A check running the process of a group once and testing one output."""

    def check(project: Project, folder: Path) -> tuple[float, bool]:
        results = load_script(project, target, folder).build_process().execute()
        value = float(results[output][0])
        return value, ok(value)

    return check


def best(scenario: Any) -> float:
    """The best objective value found."""
    return float(scenario.optimization_result.f_opt)


def samples(scenario: Any) -> int:
    """The number of evaluations of a DOE."""
    return len(scenario.to_dataset())


def check_errors(project: Project) -> list[str]:
    """The validation errors of a project."""
    problems = validate(ValidationContext(project, resolve(project)))
    return [problem.message for problem in problems if problem.level == "error"]


def surrogate_example(project: Project, folder: Path) -> float:
    """Run the DOE, train an RBF on it, then run the optimizer on the surrogate."""
    doe = run_study(project, "n-doe", folder)
    run = folder / "r-doe"
    run.mkdir()
    doe.formulation.optimization_problem.database.to_dataset().to_csv(
        run / "dataset.csv"
    )
    write_info(
        run,
        RunInfo(
            id="r-doe",
            driver="n-doe",
            driver_name="DOE",
            status="completed",
            created="2026-01-01T00:00:00",
            variables=[
                VariableInfo(name="x", role="design variable"),
                VariableInfo(name="y", role="design variable"),
                VariableInfo(name="f", role="objective"),
            ],
        ),
    )
    model = folder / "Rosenbrock.pkl"
    train(str(run), ["x", "y"], ["f"], "RBFRegressor", {}, 3, str(model))
    surrogate = project.find("n-surrogate")
    assert isinstance(surrogate, ComponentNode)
    surrogate.config = {"model_path": str(model)}
    return best(run_study(project, "n-optimizer", folder))


Check = Callable[[Project, Path], tuple[float, bool]]


def check_surrogate(project: Project, folder: Path) -> tuple[float, bool]:
    """The surrogate example gives a finite optimum."""
    value = surrogate_example(project, folder)
    return value, math.isfinite(value)


def study(
    target: str, measure: Callable[[Any], float], ok: Callable[[float], bool]
) -> Check:
    """A check running one study and testing its result."""

    def check(project: Project, folder: Path) -> tuple[float, bool]:
        value = measure(run_study(project, target, folder))
        return value, ok(value)

    return check


EXAMPLES: dict[str, Check] = {
    "sellar_mdf": study("n-optimizer", best, lambda f: abs(f - 3.18) < 0.01),
    "sellar_idf": study("n-optimizer", best, lambda f: abs(f - 3.18) < 0.01),
    "sellar_disciplinary_opt": study(
        "n-optimizer", best, lambda f: abs(f - 3.18) < 0.01
    ),
    "rosenbrock_doe": study("n-study", samples, lambda n: n == 30),
    "rosenbrock_parametric": study("n-study", samples, lambda n: n == 15),
    "doe_around_optimization": study("n-study", samples, lambda n: n == 5),
    "beam_chain": study("n-study", samples, lambda n: n == 20),
    # Material, then the optimization of the beam, then its cost.
    "optimization_sequence": process_output(
        "n-root", "cost_eur", lambda cost: abs(cost - 441.9) < 0.5
    ),
    "sobieski_bilevel": study("n-system", best, lambda f: f < -1000),
    # A maximized range: GEMSEO minimizes its opposite.
    "wing_sizing": study("n-optimizer", best, lambda f: abs(f + 2590.2) < 1),
    "external_code/external_code": study(
        "n-optimizer", best, lambda f: abs(f - 1.125) < 1e-3
    ),
    "rosenbrock_surrogate": check_surrogate,
}


def main() -> int:
    """Run the examples; the exit code is the number of failures."""
    print(f"gemseo-process-builder {gemseo_process_builder.__version__}")
    print(f"from {Path(gemseo_process_builder.__file__).parent}")
    # The surrogate training runs worker code, which waits for GEMSEO.
    load_gemseo(EventChannel(io.StringIO()))
    failures = 0
    # The demos of the Library are shipped in the package.
    folder = demos_folder()
    demos = find_demos(folder) if folder else []
    package = Path(gemseo_process_builder.__file__).parent
    shipped = folder is not None and folder.is_relative_to(package)
    print(f"{'ok  ' if shipped and demos else 'FAIL'} demos: {len(demos)} in {folder}")
    failures += not (shipped and demos)
    for name, check in EXAMPLES.items():
        start = time.perf_counter()
        project = reference(name)
        errors = check_errors(project)
        if name == "rosenbrock_surrogate":
            # Its surrogate is built by the check itself.
            errors = [error for error in errors if "surrogate" not in error.lower()]
        if errors:
            print(f"FAIL {name}: {errors}")
            failures += 1
            continue
        with tempfile.TemporaryDirectory() as folder:
            try:
                value, passed = check(project, Path(folder))
            except Exception as error:  # Reported, then the next example.
                print(f"FAIL {name}: {type(error).__name__}: {error}")
                failures += 1
                continue
        status = "ok  " if passed else "FAIL"
        failures += not passed
        print(f"{status} {name}: {value:.6g} ({time.perf_counter() - start:.1f} s)")
    print(f"{len(EXAMPLES) - failures}/{len(EXAMPLES)} examples passed.")
    return failures


if __name__ == "__main__":
    sys.exit(main())
