"""Synthetic models for the performance benchmarks (SPEC § 14.1, § 15.5).

Usage:
    python benchmarks/generate.py OUTPUT.gpb.json [--components 2000]
        [--ports 25] [--depth 6] [--big-level 300] [--samples 50000] [--seed 1]

The model is made of analytic components, so that it needs no user code:

- a "Big" assembly at the first level holds ``--big-level`` components (the
  300-node level of the canvas and auto-layout targets);
- the other components are spread over the leaves of a tree of assemblies,
  ``--depth`` levels deep with the root;
- each component has ``--ports`` variables: its outputs are named after it,
  its inputs are mostly outputs of earlier components (couplings by name),
  some are outputs of later components (loops), the others are free inputs.

With ``--samples``, a fake completed run with that many evaluations is added
to the project for the results benchmark. The same seed gives the same model.
"""

import argparse
import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path

from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import Layout
from gemseo_process_builder.core.model import Metadata
from gemseo_process_builder.core.model import NodeLayout
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.model import RunRef
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.serialization import save_project

COLUMNS = 20
"""Components per row when they are placed on a grid."""


@dataclass
class Settings:
    """The size and shape of a synthetic model."""

    components: int = 2000
    ports: int = 25
    depth: int = 6
    big_level: int = 300
    coupling: float = 0.7
    """The share of inputs coupled to an output of another component."""

    loops: float = 0.05
    """The share of coupled inputs coming from later components."""

    samples: int = 0
    seed: int = 1


def _outputs(index: int, count: int) -> list[str]:
    return [f"y{index}_{k}" for k in range(count)]


def _component(index: int, n_outputs: int, inputs: list[str]) -> ComponentNode:
    """An analytic component: each output sums two of the inputs."""
    outputs = _outputs(index, n_outputs)
    expressions = {
        name: f"0.5*{inputs[k % len(inputs)]} + 0.1*{inputs[(k + 1) % len(inputs)]}"
        for k, name in enumerate(outputs)
    }
    ports = [
        Port(local_name=name, direction="in", shape=[1], default=[1.0])
        for name in inputs
    ]
    ports += [Port(local_name=name, direction="out", shape=[1]) for name in outputs]
    return ComponentNode(
        id=f"n-c{index}",
        name=f"C{index}",
        kind="analytic",
        config={"expressions": expressions},
        ports=ports,
    )


def _source(index: int, settings: Settings, rng: random.Random) -> int | None:
    """The component an input comes from, or ``None`` for a free input."""
    if settings.components < 2 or rng.random() >= settings.coupling:
        return None
    earlier = range(index)
    later = range(index + 1, settings.components)
    if later and (not earlier or rng.random() < settings.loops):
        return rng.choice(later)
    return rng.choice(earlier)


def _inputs(index: int, settings: Settings, rng: random.Random) -> list[str]:
    """The inputs of a component: outputs of other components, or free inputs."""
    n_outputs = settings.ports - settings.ports // 2
    names: list[str] = []
    for k in range(settings.ports // 2):
        source = _source(index, settings, rng)
        name = (
            f"x{index}_{k}"
            if source is None
            else f"y{source}_{rng.randrange(n_outputs)}"
        )
        # The same output twice would be one input: a free input replaces it.
        names.append(name if name not in names else f"x{index}_{k}")
    return names or [f"x{index}_0"]


def _tree(
    components: list[ComponentNode], depth: int, prefix: str
) -> list[ComponentNode | AssemblyNode]:
    """The components in two assemblies per level, ``depth`` levels deep."""
    if depth <= 0 or len(components) < 4:
        return list(components)
    half = len(components) // 2
    return [
        AssemblyNode(
            id=f"n-{prefix}{side}",
            name=f"{prefix.upper()}{side}",
            children=_tree(part, depth - 1, f"{prefix}{side}"),
        )
        for side, part in (("a", components[:half]), ("b", components[half:]))
    ]


def _grid(nodes: list[str], layout: Layout) -> None:
    for position, node_id in enumerate(nodes):
        layout.nodes[node_id] = NodeLayout(
            x=40.0 + 260.0 * (position % COLUMNS),
            y=40.0 + 360.0 * (position // COLUMNS),
        )


def generate(settings: Settings) -> Project:
    """A synthetic project; the same settings give the same project."""
    rng = random.Random(settings.seed)
    n_outputs = settings.ports - settings.ports // 2
    components = [
        _component(index, n_outputs, _inputs(index, settings, rng))
        for index in range(settings.components)
    ]
    big = AssemblyNode(
        id="n-big", name="Big", children=list(components[: settings.big_level])
    )
    # Levels: the root, "Tree", its assemblies, and the components inside.
    tree = AssemblyNode(
        id="n-tree",
        name="Tree",
        children=_tree(components[settings.big_level :], settings.depth - 3, "t"),
    )
    project = Project(
        metadata=Metadata(name=f"Synthetic {settings.components}"),
        root=AssemblyNode(id="n-root", name="Model", children=[big, tree]),
    )
    _grid(["n-big", "n-tree"], project.layout)
    for node, _ in _containers(project.root):
        _grid([child.id for child in node.children], project.layout)
    return project


def _containers(node: AssemblyNode) -> list[tuple[AssemblyNode, int]]:
    """The assemblies of a tree, the given one first."""
    found = [(node, 0)]
    for child in node.children:
        if isinstance(child, AssemblyNode):
            found.extend(_containers(child))
    return found


def write_run(project: Project, project_file: Path, samples: int, seed: int) -> None:
    """Add a fake completed DOE run of ``samples`` evaluations to the project."""
    rng = random.Random(seed)
    folder = project_file.parent / f"{project.metadata.name}.runs" / "r-benchmark"
    folder.mkdir(parents=True, exist_ok=True)
    inputs = [f"x{k}" for k in range(4)]
    outputs = [f"f{k}" for k in range(6)]
    with (folder / "dataset.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            ["GROUP", *["inputs"] * len(inputs), *["outputs"] * len(outputs)]
        )
        writer.writerow(["VARIABLE", *inputs, *outputs])
        writer.writerow(["COMPONENT", *["0"] * (len(inputs) + len(outputs))])
        for row in range(samples):
            x = [rng.uniform(-1.0, 1.0) for _ in inputs]
            f = [
                sum(value * (k + 1) for value in x) + rng.gauss(0, 0.1)
                for k in range(len(outputs))
            ]
            writer.writerow([row, *(f"{value:.6g}" for value in x + f)])
    info = {
        "schema_version": 1,
        "id": "r-benchmark",
        "driver": "n-root",
        "driver_name": "Benchmark",
        "status": "completed",
        "created": "2026-01-01T00:00:00",
        "summary": {"n_evaluations": samples},
        "variables": [
            *(
                {
                    "name": name,
                    "role": "design variable",
                    "lower": [-1.0],
                    "upper": [1.0],
                }
                for name in inputs
            ),
            *({"name": name, "role": "observable"} for name in outputs),
        ],
    }
    (folder / "run.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    project.runs.append(
        RunRef(
            id="r-benchmark",
            driver="n-root",
            run_path=f"{project.metadata.name}.runs/r-benchmark",
        )
    )


def main() -> None:
    """Write a synthetic project from the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path)
    defaults = Settings()
    for name in ("components", "ports", "depth", "big_level", "samples", "seed"):
        parser.add_argument(
            f"--{name.replace('_', '-')}", type=int, default=getattr(defaults, name)
        )
    arguments = parser.parse_args()
    settings = Settings(
        **{
            name: getattr(arguments, name)
            for name in ("components", "ports", "depth", "big_level", "samples", "seed")
        }
    )
    project = generate(settings)
    if settings.samples:
        write_run(project, arguments.output, settings.samples, settings.seed)
    save_project(project, arguments.output)
    variables = sum(
        len(node.ports)
        for node, _ in iter_nodes(project.root)
        if isinstance(node, ComponentNode)
    )
    print(f"Wrote {arguments.output}: {settings.components} components,", end=" ")
    print(f"{variables} variables.")


if __name__ == "__main__":
    main()
