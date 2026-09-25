"""The projects whose generated scripts are stored in ``codegen/golden/``."""

from collections.abc import Callable
from functools import partial
from pathlib import Path

from builders import assembly
from builders import component
from builders import driver
from builders import project

from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import Endpoint
from gemseo_process_builder.core.model import Link
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.serialization import load_project

SELLAR = "gemseo.problems.mdo.sellar"


def _sellar_class(
    name: str, module: str, ins: list[str], outs: list[str]
) -> ComponentNode:
    return component(
        name,
        ins,
        outs,
        kind="python_class",
        config={"module": f"{SELLAR}.{module}", "class": name},
    )


def sellar_mda() -> Project:
    """The three Sellar disciplines of GEMSEO in an MDA driver."""
    sellar = project(
        driver(
            "SellarMDA",
            "mda",
            _sellar_class(
                "Sellar1", "sellar_1", ["x_1", "x_shared", "y_2", "gamma"], ["y_1"]
            ),
            _sellar_class("Sellar2", "sellar_2", ["x_2", "x_shared", "y_1"], ["y_2"]),
            _sellar_class(
                "SellarSystem",
                "sellar_system",
                ["x_1", "x_2", "x_shared", "y_1", "y_2", "alpha", "beta"],
                ["obj", "c_1", "c_2"],
            ),
            config={"mda_settings": {"tolerance": 1e-10, "max_mda_iter": 50}},
        )
    )
    sellar.metadata.name = "Sellar"
    return sellar


def _type_value(node: ComponentNode, index: int, value: float, text: str) -> None:
    """Set the value of a port as if the user typed ``text``."""
    node.ports[index] = node.ports[index].model_copy(
        update={"default": value, "default_text": text}
    )


def analytic_chain() -> Project:
    """Two analytic disciplines, one after the other, with typed input values."""
    area = component("Area", ["length", "width"], ["area"])
    area.config = {"expressions": {"area": "length*width"}}
    _type_value(area, 0, 2.0, "2.0")
    _type_value(area, 1, 1e-1, "1e-1")
    cost = component("Cost", ["area"], ["cost"])
    cost.config = {"expressions": {"cost": "12.5*area + 3"}}
    chain = project(cost, area)
    chain.metadata.name = "Panel cost"
    return chain


def parallel_assembly() -> Project:
    """Two independent analytic disciplines run in parallel, then a sum."""
    left = component("LeftWing", ["span"], ["lift_left"])
    left.config = {"expressions": {"lift_left": "0.5*span"}}
    right = component("RightWing", ["span"], ["lift_right"])
    right.config = {"expressions": {"lift_right": "0.5*span"}}
    total = component("TotalLift", ["lift_left", "lift_right"], ["lift"])
    total.config = {"expressions": {"lift": "lift_left + lift_right"}}
    wings = assembly("Wings", left, right, mode="parallel")
    aircraft = project(wings, total)
    aircraft.root.mode = "chain"
    aircraft.metadata.name = "Aircraft"
    return aircraft


def remapped_link() -> Project:
    """An explicit link between variables with different names."""
    source = component("Source", ["x"], ["temperature"])
    source.config = {"expressions": {"temperature": "300 + 2*x"}}
    sink = component("Sink", ["t_in"], ["stress"])
    sink.config = {"expressions": {"stress": "0.01*t_in"}}
    linked = project(source, sink)
    linked.links.append(
        Link(
            source=Endpoint(node="n-Source", port="temperature"),
            target=Endpoint(node="n-Sink", port="t_in"),
        )
    )
    linked.metadata.name = "Thermal stress"
    return linked


def isolated_instances() -> Project:
    """Two isolated instances of one discipline, fed by a shared input."""
    formula = {"expressions": {"mass": "density*volume"}}
    front = component("Front", ["density", "volume"], ["mass"], isolated=True)
    rear = component("Rear", ["density", "volume"], ["mass"], isolated=True)
    front.config = rear.config = formula
    for part, volume in ((front, "2.5"), (rear, "1.5")):
        part.ports[0] = part.ports[0].model_copy(update={"global_name": "density"})
        _type_value(part, 1, float(volume), volume)
    _type_value(front, 0, 7800.0, "7800")
    total = component("TotalMass", ["front_mass", "rear_mass"], ["total_mass"])
    total.config = {"expressions": {"total_mass": "front_mass + rear_mass"}}
    parts = project(front, rear, total)
    for part in ("Front", "Rear"):
        parts.links.append(
            Link(
                source=Endpoint(node=f"n-{part}", port="mass"),
                target=Endpoint(node="n-TotalMass", port=f"{part.lower()}_mass"),
            )
        )
    parts.metadata.name = "Masses"
    return parts


def units_conversion() -> Project:
    """A plate in mm and degC feeding a stress model in m and K."""
    plate = component("Plate", ["width"], ["thickness", "temperature"])
    plate.config = {
        "expressions": {"thickness": "0.1*width", "temperature": "20 + 0*width"}
    }
    _type_value(plate, 0, 10.0, "10.0")
    for index, unit in ((0, "mm"), (1, "mm"), (2, "degC")):
        plate.ports[index] = plate.ports[index].model_copy(update={"unit": unit})
    stress = component("Stress", ["thickness", "temperature"], ["stress"])
    stress.config = {"expressions": {"stress": "1000*thickness + temperature"}}
    for index, unit in ((0, "m"), (1, "K")):
        stress.ports[index] = stress.ports[index].model_copy(update={"unit": unit})
    model = project(plate, stress)
    model.metadata.name = "Plate stress"
    return model


GOLDEN_PROJECTS: dict[str, Callable[[], Project]] = {
    "sellar_mda": sellar_mda,
    "analytic_chain": analytic_chain,
    "parallel_assembly": parallel_assembly,
    "remapped_link": remapped_link,
    "isolated_instances": isolated_instances,
    "units_conversion": units_conversion,
}
"""The name of each golden file and the project it is generated from."""

TARGETS = {"sellar_mda": "n-SellarMDA"}
"""The node to run when it is not the root."""

EXAMPLES = Path(__file__).parents[2] / "examples"
"""The reference projects of SPEC § 15.3, run by the driver at the root."""

EXAMPLE_TARGETS = {
    "sellar_mdf": "n-optimizer",
    "sellar_idf": "n-optimizer",
    "sellar_disciplinary_opt": "n-optimizer",
    "rosenbrock_doe": "n-study",
    "rosenbrock_parametric": "n-study",
    "doe_around_optimization": "n-study",
    "sobieski_bilevel": "n-system",
}


def example(name: str) -> Project:
    """An example project of the repository."""
    return load_project(EXAMPLES / f"{name}.gpb.json")


for _name, _target in EXAMPLE_TARGETS.items():
    GOLDEN_PROJECTS[_name] = partial(example, _name)
    TARGETS[_name] = _target
