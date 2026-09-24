"""Write the reference projects of ``examples/`` (SPEC § 15.3).

Usage:
    python tools/build_examples.py

The examples are regular project files that can be edited in the
application; this script only exists to create them again from scratch.
"""

from pathlib import Path
from typing import Any

from gemseo_process_builder.core.model import AssemblyNode
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Layout
from gemseo_process_builder.core.model import Metadata
from gemseo_process_builder.core.model import NodeLayout
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.serialization import save_project

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
SELLAR = "gemseo.problems.mdo.sellar"

SELLAR_DESIGN_SPACE = [
    {"variable": "x_1", "lower": [0.0], "upper": [10.0], "value": [1.0]},
    {"variable": "x_2", "lower": [0.0], "upper": [10.0], "value": [1.0]},
    {
        "variable": "x_shared",
        "size": 2,
        "lower": [-10.0, 0.0],
        "upper": [10.0, 10.0],
        "value": [4.0, 3.0],
    },
]
SELLAR_PROBLEM = {
    "design_space": SELLAR_DESIGN_SPACE,
    "objectives": [{"variable": "obj"}],
    "constraints": [{"variable": "c_1"}, {"variable": "c_2"}],
    "algorithm": {"name": "SLSQP", "settings": {"max_iter": 100}},
}


def port(name: str, direction: str, default: Any = None) -> Port:
    """A float port; its shape follows its default value."""
    values = default if isinstance(default, list) else [default]
    return Port(
        local_name=name,
        direction=direction,  # type: ignore[arg-type]
        shape=[len(values)] if default is not None else [1],
        default=default,
    )


def sellar_disciplines() -> list[ComponentNode]:
    """The three Sellar disciplines of GEMSEO, with the ports they introspect to."""

    def discipline(
        name: str, module: str, ins: dict[str, Any], outs: list[str]
    ) -> ComponentNode:
        ports = [port(n, "in", value) for n, value in ins.items()]
        ports += [port(n, "out") for n in outs]
        return ComponentNode(
            id=f"n-{name.lower()}",
            name=name,
            kind="python_class",
            config={"module": f"{SELLAR}.{module}", "class": name, "init_args": {}},
            ports=ports,
        )

    return [
        discipline(
            "Sellar1",
            "sellar_1",
            {"x_1": [0.0], "x_shared": [1.0, 0.0], "y_2": [1.0], "gamma": [0.2]},
            ["y_1"],
        ),
        discipline(
            "Sellar2",
            "sellar_2",
            {"x_2": [0.0], "x_shared": [1.0, 0.0], "y_1": [1.0]},
            ["y_2"],
        ),
        discipline(
            "SellarSystem",
            "sellar_system",
            {
                "x_1": [0.0],
                "x_2": [0.0],
                "x_shared": [1.0, 0.0],
                "y_1": [1.0],
                "y_2": [1.0],
                "alpha": [3.16],
                "beta": [24.0],
            },
            ["obj", "c_1", "c_2"],
        ),
    ]


def with_layout(project: Project, positions: dict[str, tuple[float, float]]) -> Project:
    """Place the nodes on the canvas."""
    project.layout = Layout(
        nodes={node: NodeLayout(x=x, y=y) for node, (x, y) in positions.items()}
    )
    return project


def sellar(formulation: str, title: str) -> Project:
    """The Sellar optimization with one formulation."""
    config: dict[str, Any] = {**SELLAR_PROBLEM}
    if formulation == "IDF":
        # With IDF, the optimizer also sets the coupling variables.
        config["design_space"] = SELLAR_DESIGN_SPACE + [
            {"variable": name, "lower": [-100.0], "upper": [100.0], "value": [1.0]}
            for name in ("y_1", "y_2")
        ]
    if formulation != "MDF":
        config["formulation"] = {"name": formulation}
    else:
        config["formulation"] = {
            "name": "MDF",
            "settings": {"main_mda_name": "MDAGaussSeidel"},
        }
    disciplines = sellar_disciplines()
    children: list[Any] = disciplines
    positions = {"n-optimizer": (80.0, 60.0)}
    if formulation == "DisciplinaryOpt":
        # The optimizer sees one discipline: an MDA solving the couplings.
        children = [
            AssemblyNode(
                id="n-sellar-mda", name="SellarMDA", mode="mda", children=disciplines
            )
        ]
        positions["n-sellar-mda"] = (40.0, 40.0)
    for index, node in enumerate(disciplines):
        positions[node.id] = (40.0 + 280.0 * index, 60.0)
    optimizer = DriverNode(
        id="n-optimizer",
        name="Optimizer",
        kind="optimization",
        config=config,
        children=children,
    )
    project = Project(
        metadata=Metadata(name=title),
        root=AssemblyNode(id="n-root", name="Model", children=[optimizer]),
    )
    return with_layout(project, positions)


def rosenbrock(kind: str, title: str, config: dict[str, Any]) -> Project:
    """A study of the Rosenbrock function."""
    function = ComponentNode(
        id="n-rosenbrock",
        name="Rosenbrock",
        kind="analytic",
        config={"expressions": {"f": "(1 - x)**2 + 100*(y - x**2)**2"}},
        ports=[port("x", "in", 0.0), port("y", "in", 0.0), port("f", "out")],
    )
    study = DriverNode(
        id="n-study",
        name="Study",
        kind=kind,
        config=config,
        children=[function],
    )
    project = Project(
        metadata=Metadata(name=title),
        root=AssemblyNode(id="n-root", name="Model", children=[study]),
    )
    return with_layout(project, {"n-study": (80.0, 60.0), "n-rosenbrock": (40.0, 60.0)})


def examples() -> dict[str, Project]:
    """The example projects by file name."""
    bounds = [
        {"variable": "x", "lower": [-2.0], "upper": [2.0]},
        {"variable": "y", "lower": [-2.0], "upper": [2.0]},
    ]
    return {
        "sellar_mdf": sellar("MDF", "Sellar MDF"),
        "sellar_idf": sellar("IDF", "Sellar IDF"),
        "sellar_disciplinary_opt": sellar("DisciplinaryOpt", "Sellar DisciplinaryOpt"),
        "rosenbrock_doe": rosenbrock(
            "doe",
            "Rosenbrock DOE",
            {
                "design_space": bounds,
                "responses": ["f"],
                "algorithm": {"name": "LHS", "settings": {"n_samples": 30, "seed": 1}},
            },
        ),
        "rosenbrock_parametric": rosenbrock(
            "parametric",
            "Rosenbrock parametric study",
            {
                "levels": [
                    {"variable": "x", "lower": -2.0, "upper": 2.0, "count": 5},
                    {"variable": "y", "mode": "list", "values": [0.0, 1.0, 2.0]},
                ],
                "responses": ["f"],
            },
        ),
    }


def main() -> None:
    EXAMPLES.mkdir(exist_ok=True)
    for name, project in examples().items():
        save_project(project, EXAMPLES / f"{name}.gpb.json")
        print(f"Wrote examples/{name}.gpb.json")


if __name__ == "__main__":
    main()
