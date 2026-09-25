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
SOBIESKI = "gemseo.problems.mdo.sobieski.disciplines"

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


def port(name: str, direction: str, default: Any = None, size: int = 1) -> Port:
    """A float port; its shape follows its default value, else ``size``."""
    values = default if isinstance(default, list) else [default]
    return Port(
        local_name=name,
        direction=direction,  # type: ignore[arg-type]
        shape=[len(values)] if default is not None else [size],
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


def doe_around_optimization() -> Project:
    """A DOE on alpha around the Sellar MDF optimization (SPEC § 6.3).

    Each sample runs a whole optimization: how does the optimum change with
    the limit ``alpha`` of the constraint ``c_1 = alpha - y_1``?
    """
    config: dict[str, Any] = {
        **SELLAR_PROBLEM,
        "formulation": {"name": "MDF", "settings": {"main_mda_name": "MDAGaussSeidel"}},
        "algorithm": {"name": "SLSQP", "settings": {"max_iter": 30}},
        "interface": {
            "inputs": ["alpha"],
            "outputs": ["obj", "x_1", "x_shared"],
            "reset_x0_before_opt": True,
        },
    }
    disciplines = sellar_disciplines()
    optimizer = DriverNode(
        id="n-optimizer",
        name="Optimizer",
        kind="optimization",
        config=config,
        children=disciplines,
    )
    study = DriverNode(
        id="n-study",
        name="Study",
        kind="doe",
        config={
            "design_space": [
                {"variable": "alpha", "lower": [3.0], "upper": [4.0], "value": [3.16]}
            ],
            "responses": ["obj", "x_1", "x_shared"],
            "algorithm": {"name": "LHS", "settings": {"n_samples": 5, "seed": 1}},
        },
        children=[optimizer],
    )
    project = Project(
        metadata=Metadata(name="Sellar DOE around optimization"),
        root=AssemblyNode(id="n-root", name="Model", children=[study]),
    )
    positions = {"n-study": (80.0, 60.0), "n-optimizer": (40.0, 60.0)}
    for index, node in enumerate(disciplines):
        positions[node.id] = (40.0 + 280.0 * index, 60.0)
    return with_layout(project, positions)


SOBIESKI_SHARED = [0.05, 45000.0, 1.6, 5.5, 55.0, 1000.0]


def sobieski_disciplines() -> dict[str, ComponentNode]:
    """The four SSBJ disciplines of GEMSEO, with the ports they introspect to."""

    def discipline(
        name: str, ins: dict[str, Any], outs: dict[str, int]
    ) -> ComponentNode:
        ports = [port(n, "in", value) for n, value in ins.items()]
        ports += [port(n, "out", size=size) for n, size in outs.items()]
        return ComponentNode(
            id=f"n-{name.lower()}",
            name=name,
            kind="python_class",
            config={"module": SOBIESKI, "class": f"Sobieski{name}", "init_args": {}},
            ports=ports,
        )

    return {
        "Structure": discipline(
            "Structure",
            {
                "y_21": [50606.9741711],
                "y_31": [6354.32430691],
                "x_1": [0.25, 1.0],
                "x_shared": SOBIESKI_SHARED,
                "c_0": [2000.0],
                "c_1": [25000.0],
                "c_2": [6.0],
            },
            {"y_1": 3, "y_11": 1, "y_14": 2, "g_1": 7, "y_12": 2},
        ),
        "Aerodynamics": discipline(
            "Aerodynamics",
            {
                "x_2": [1.0],
                "y_32": [0.50279625],
                "x_shared": SOBIESKI_SHARED,
                "y_12": [50606.9742, 0.95],
                "c_4": [0.01375],
            },
            {"y_21": 1, "y_23": 1, "y_24": 1, "g_2": 1, "y_2": 3},
        ),
        "Propulsion": discipline(
            "Propulsion",
            {
                "y_23": [12562.01206488],
                "x_3": [0.5],
                "x_shared": SOBIESKI_SHARED,
                "c_3": [4360.0],
            },
            {"y_32": 1, "y_31": 1, "g_3": 4, "y_3": 3, "y_34": 1},
        ),
        "Mission": discipline(
            "Mission",
            {
                "y_14": [50606.9741711, 7306.20262124],
                "x_shared": SOBIESKI_SHARED,
                "y_24": [4.15006276],
                "y_34": [1.10754577],
            },
            {"y_4": 1},
        ),
    }


def sobieski_bilevel() -> Project:
    """The SSBJ BiLevel optimization of GEMSEO's examples (SPEC § 6.2).

    The system optimizer sets the shared variables to maximize the range;
    each discipline optimizes its own variables in a sub-optimization.
    """
    disciplines = sobieski_disciplines()
    subs = []
    for name, variable, objective, sense, constraint in (
        (
            "Propulsion",
            {"variable": "x_3", "lower": [0.1], "upper": [1.0], "value": [0.5]},
            "y_34",
            "minimize",
            "g_3",
        ),
        (
            "Aerodynamics",
            {"variable": "x_2", "lower": [0.75], "upper": [1.25], "value": [1.0]},
            "y_24",
            "maximize",
            "g_2",
        ),
        (
            "Structure",
            {
                "variable": "x_1",
                "size": 2,
                "lower": [0.1, 0.75],
                "upper": [0.4, 1.25],
                "value": [0.25, 1.0],
            },
            "y_11",
            "maximize",
            "g_1",
        ),
    ):
        subs.append(
            DriverNode(
                id=f"n-{name.lower()}-optimizer",
                name=f"{name}Optimizer",
                kind="optimization",
                config={
                    "design_space": [variable],
                    "objectives": [{"variable": objective, "sense": sense}],
                    "constraints": [{"variable": constraint}],
                    "formulation": {"name": "DisciplinaryOpt"},
                    "algorithm": {"name": "SLSQP", "settings": {"max_iter": 30}},
                },
                children=[disciplines[name]],
            )
        )
    system = DriverNode(
        id="n-system",
        name="System",
        kind="optimization",
        config={
            "design_space": [
                {
                    "variable": "x_shared",
                    "size": 6,
                    "lower": [0.01, 30000.0, 1.4, 2.5, 40.0, 500.0],
                    "upper": [0.09, 60000.0, 1.8, 8.5, 70.0, 1500.0],
                    "value": SOBIESKI_SHARED,
                }
            ],
            "objectives": [{"variable": "y_4", "sense": "maximize"}],
            "constraints": [
                {"variable": "g_1"},
                {"variable": "g_2"},
                {"variable": "g_3"},
            ],
            "formulation": {
                "name": "BiLevel",
                "settings": {"apply_cstr_tosub_scenarios": False},
            },
            "algorithm": {"name": "COBYQA", "settings": {"max_iter": 20}},
        },
        children=[*subs, disciplines["Mission"]],
    )
    project = Project(
        metadata=Metadata(name="Sobieski BiLevel"),
        root=AssemblyNode(id="n-root", name="Model", children=[system]),
    )
    positions = {"n-system": (80.0, 60.0), "n-mission": (40.0, 400.0)}
    for index, sub in enumerate(subs):
        positions[sub.id] = (40.0 + 300.0 * index, 60.0)
        positions[sub.children[0].id] = (40.0, 60.0)
    return with_layout(project, positions)


def external_code() -> Project:
    """An optimization of an external code run through its wrapper (SPEC § 7.5)."""
    descriptor = EXAMPLES / "external_code" / "solver.gpbwrap.json"
    solver = ComponentNode(
        id="n-solver",
        name="Solver",
        kind="executable",
        config={"descriptor_path": str(descriptor)},
        ports=[
            port("x", "in", [0.0]),
            port("y", "in", [0.0]),
            port("f", "out"),
            port("g", "out"),
        ],
    )
    optimizer = DriverNode(
        id="n-optimizer",
        name="Optimizer",
        kind="optimization",
        config={
            "design_space": [
                {"variable": name, "lower": [-5.0], "upper": [5.0], "value": [0.0]}
                for name in ("x", "y")
            ],
            "objectives": [{"variable": "f"}],
            "constraints": [{"variable": "g"}],
            "formulation": {"name": "DisciplinaryOpt"},
            "algorithm": {"name": "SLSQP", "settings": {"max_iter": 20}},
        },
        children=[solver],
    )
    project = Project(
        metadata=Metadata(name="External code"),
        root=AssemblyNode(id="n-root", name="Model", children=[optimizer]),
    )
    return with_layout(project, {"n-optimizer": (80.0, 60.0), "n-solver": (40.0, 60.0)})


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


def rosenbrock_surrogate() -> Project:
    """A DOE of the Rosenbrock function, then an optimization on its surrogate.

    The surrogate is built in the application from a run of the DOE (SPEC § 7.4):
    the example ships without it.
    """
    bounds = [
        {"variable": name, "lower": [-2.0], "upper": [2.0], "value": [0.0]}
        for name in ("x", "y")
    ]
    doe = rosenbrock(
        "doe",
        "",
        {
            "design_space": [
                {key: value for key, value in item.items() if key != "value"}
                for item in bounds
            ],
            "responses": ["f"],
            "algorithm": {"name": "LHS", "settings": {"n_samples": 30, "seed": 1}},
        },
    ).root.children[0]
    doe.id, doe.name = "n-doe", "DOE"
    surrogate = ComponentNode(
        id="n-surrogate",
        name="Surrogate",
        kind="surrogate",
        ports=[port("x", "in", 0.0), port("y", "in", 0.0), port("f", "out")],
    )
    optimizer = DriverNode(
        id="n-optimizer",
        name="Optimizer",
        kind="optimization",
        config={
            "design_space": bounds,
            "objectives": [{"variable": "f"}],
            "formulation": {"name": "DisciplinaryOpt"},
            "algorithm": {"name": "SLSQP", "settings": {"max_iter": 50}},
        },
        children=[surrogate],
    )
    project = Project(
        metadata=Metadata(
            name="Rosenbrock surrogate",
            description=(
                "Run the DOE, build a surrogate from its run (Runs panel: Build "
                "surrogate), give it to the Surrogate component, then run the "
                "optimizer: it optimizes the surrogate instead of the function."
            ),
        ),
        root=AssemblyNode(id="n-root", name="Model", children=[doe, optimizer]),
    )
    return with_layout(
        project,
        {
            "n-doe": (60.0, 60.0),
            "n-rosenbrock": (40.0, 60.0),
            "n-optimizer": (420.0, 60.0),
            "n-surrogate": (40.0, 60.0),
        },
    )


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
        "doe_around_optimization": doe_around_optimization(),
        "sobieski_bilevel": sobieski_bilevel(),
        "external_code/external_code": external_code(),
        "rosenbrock_surrogate": rosenbrock_surrogate(),
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
