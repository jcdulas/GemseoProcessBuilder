"""The synthetic models of the benchmarks."""

import importlib.util
from pathlib import Path
from types import ModuleType

from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.resolver import resolve

GENERATE = Path(__file__).parents[3] / "benchmarks" / "generate.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("benchmark_generate", GENERATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def depth_of(node: AssemblyNode) -> int:
    children = [child for child in node.children if isinstance(child, AssemblyNode)]
    return 1 + max((depth_of(child) for child in children), default=0)


def test_structure_and_determinism() -> None:
    generate = load()
    settings = generate.Settings(components=60, ports=10, depth=5, big_level=20)
    project = generate.generate(settings)
    components = [
        node for node, _ in iter_nodes(project.root) if isinstance(node, ComponentNode)
    ]
    assert len(components) == 60
    assert sum(len(node.ports) for node in components) == 600
    assert len(project.find("n-big").children) == 20  # type: ignore[union-attr]
    # The root, "Tree", its assemblies, then the leaves holding the components.
    assert depth_of(project.root) == 4
    assert generate.generate(settings) == project
    # Components are coupled by name, with a few loops.
    resolution = resolve(project)
    assert any(resolution.couplings.values())


def test_fake_run(tmp_path: Path) -> None:
    generate = load()
    project = generate.generate(generate.Settings(components=4, ports=4, big_level=2))
    generate.write_run(project, tmp_path / "model.gpb.json", 10, 1)
    folder = tmp_path / f"{project.metadata.name}.runs" / "r-benchmark"
    lines = (folder / "dataset.csv").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3 + 10
    assert project.runs[0].id == "r-benchmark"
