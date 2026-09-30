"""Working examples of components, created from the inspector.

``componentExample.create`` fills a component that is not set up yet with an
example that runs:

- a Python function or a Python class: a module in a file the user chooses;
- an executable wrapper: a small external program, its input template and its
  descriptor, in the folder of the descriptor the user chooses;
- a surrogate: a run of example samples in the project; the page then trains
  a surrogate on it and uses it, as the Build surrogate wizard does.

Every example is the same rectangular wing, whose area and aspect ratio come
from its span and chord (the executable wrapper keeps the solver of
``examples/external_code``). Existing files are never replaced.
"""

import random
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.app.run_manager import new_run_id
from gemseo_process_builder.core.atomic_write import write_text_atomically
from gemseo_process_builder.core.commands import CommandError
from gemseo_process_builder.core.commands import SetNodeProperties
from gemseo_process_builder.core.discipline_file import FileVariable
from gemseo_process_builder.core.discipline_file import new_module
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.results.models import RunInfo
from gemseo_process_builder.results.models import RunSummary
from gemseo_process_builder.results.models import VariableInfo
from gemseo_process_builder.results.models import write_info
from gemseo_process_builder.results.store import RunStore

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

WING_INPUTS = [
    FileVariable("span", "in", values=[10.0]),
    FileVariable("chord", "in", values=[2.0]),
]
WING_OUTPUTS = [FileVariable("area", "out"), FileVariable("aspect_ratio", "out")]
WING_COMPUTATION = ["area = span * chord", "aspect_ratio = span / chord"]
WING_DESCRIPTION = "The area and the aspect ratio of a rectangular wing"

BOUNDS = {"span": (5.0, 20.0), "chord": (1.0, 4.0)}
"""The ranges of the example samples of the surrogate."""

N_SAMPLES = 40
SURROGATE_ALGORITHM = "RBFRegressor"


class ExampleParams(BaseModel):
    """Parameters of ``componentExample.create``."""

    id: str
    path: str = ""
    """The file to write: the module, or the descriptor of a wrapper."""


def latin_hypercube(
    bounds: dict[str, tuple[float, float]], n_samples: int, seed: int = 1
) -> dict[str, list[float]]:
    """Samples spread over the ranges: one per slice of each range."""
    generator = random.Random(seed)
    samples = {}
    for name, (low, high) in bounds.items():
        slices = list(range(n_samples))
        generator.shuffle(slices)
        width = (high - low) / n_samples
        samples[name] = [low + (index + generator.random()) * width for index in slices]
    return samples


def _free(paths: list[Path]) -> None:
    """Refuse to replace files."""
    existing = [path.name for path in paths if path.exists()]
    if existing:
        msg = (
            f"{', '.join(existing)} already exist: choose another folder or name, "
            "they are not replaced."
        )
        raise BridgeError(ErrorCode.CONFLICT, msg)


class ComponentExamples:
    """Create working examples of components."""

    def __init__(
        self,
        session: ProjectSession,
        bridge: Bridge,
        runs: RunStore,
    ) -> None:
        self.session = session
        self.bridge = bridge
        self.runs = runs

    def _component(self, node_id: str) -> ComponentNode:
        node = self.session.project.find(node_id)
        if not isinstance(node, ComponentNode):
            raise BridgeError(ErrorCode.NOT_FOUND, f"No component {node_id}.")
        return node

    def _configure(self, node: ComponentNode, config: dict[str, Any]) -> None:
        try:
            self.session.document.execute(
                SetNodeProperties(
                    id=node.id,
                    values={"config": config},
                    label_text="Create an example",
                )
            )
        except CommandError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None

    def _path(self, params: ExampleParams, suffix: str) -> Path:
        if not params.path:
            msg = "Choose where to write the example."
            raise BridgeError(ErrorCode.INVALID_PARAMS, msg)
        path = Path(params.path)
        return path if path.name.endswith(suffix) else path.with_suffix(suffix)

    def create(self, params: ExampleParams) -> dict[str, Any]:
        """Fill a component with a working example; return what was written."""
        node = self._component(params.id)
        if node.kind == "python_function":
            path = self._path(params, ".py")
            _free([path])
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(TEMPLATES / "wing_function.py", path)
            self._configure(node, {"module_path": str(path), "function": "wing_area"})
            return {"files": [str(path)]}
        if node.kind == "python_class":
            path = self._path(params, ".py")
            _free([path])
            source = new_module(
                "Wing", WING_DESCRIPTION, WING_INPUTS + WING_OUTPUTS, WING_COMPUTATION
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomically(path, source)
            self._configure(
                node, {"module_path": str(path), "class": "Wing", "init_args": {}}
            )
            return {"files": [str(path)]}
        if node.kind == "executable":
            descriptor = self._path(params, ".gpbwrap.json")
            folder = descriptor.parent
            templates = sorted(
                path
                for path in (TEMPLATES / "external_code").iterdir()
                if path.is_file()
            )
            targets = [
                descriptor if template.suffix == ".json" else folder / template.name
                for template in templates
            ]
            _free(targets)
            folder.mkdir(parents=True, exist_ok=True)
            for template, target in zip(templates, targets, strict=True):
                shutil.copyfile(template, target)
            self._configure(node, {"descriptor_path": str(descriptor)})
            return {"files": [str(target) for target in targets]}
        msg = f"There is no example of {node.kind} components."
        raise BridgeError(ErrorCode.INVALID_PARAMS, msg)

    def example_run(self) -> str:
        """Write a run of example samples of the wing in the project; its id."""
        folder = self.runs.folder()
        run_id = new_run_id(folder)
        run = folder / run_id
        run.mkdir(parents=True)
        samples = latin_hypercube(BOUNDS, N_SAMPLES)
        names = [*BOUNDS, "area", "aspect_ratio"]
        rows = []
        for index in range(N_SAMPLES):
            span, chord = samples["span"][index], samples["chord"][index]
            values = [span, chord, span * chord, span / chord]
            rows.append(f"{index}," + ",".join(repr(value) for value in values))
        header = [
            "GROUP," + ",".join(["inputs"] * 2 + ["outputs"] * 2),
            "VARIABLE," + ",".join(names),
            "COMPONENT," + ",".join(["0"] * len(names)),
        ]
        (run / "dataset.csv").write_text("\n".join(header + rows) + "\n", "utf-8")
        stamp = datetime.now().isoformat(timespec="seconds")
        info = RunInfo(
            id=run_id,
            name="Example samples of a wing",
            driver="",
            driver_name="Example",
            algorithm="LHS",
            status="completed",
            created=stamp,
            started=stamp,
            finished=stamp,
            summary=RunSummary(n_evaluations=N_SAMPLES),
            variables=[
                VariableInfo(
                    name=name, role="design variable", lower=[low], upper=[high]
                )
                for name, (low, high) in BOUNDS.items()
            ]
            + [VariableInfo(name=name, role="output") for name in names[2:]],
        )
        write_info(run, info)
        self.runs.add(info, run)
        self.bridge.emit_event("runs.changed", None)
        return run_id

    def samples(self) -> dict[str, Any]:
        """The example run of a surrogate, and how to train on it.

        The page then trains the surrogate with ``surrogates.train`` and keeps
        it with ``surrogates.save``, as the Build surrogate wizard does.
        """
        return {
            "run": self.example_run(),
            "inputs": list(BOUNDS),
            "outputs": ["area", "aspect_ratio"],
            "algorithm": SURROGATE_ALGORITHM,
            "name": "Wing example",
        }

    def register(self) -> None:
        """Register the ``componentExample.*`` methods."""
        registry = self.bridge.registry
        registry.add("componentExample.create", self.create)
        registry.add("componentExample.samples", self.samples)
