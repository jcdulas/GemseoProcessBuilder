"""One triggering and one clean case per unit and type rule."""

from typing import Any

from builders import component
from builders import driver
from builders import project

from gemseo_process_builder.core.commands import parse_command
from gemseo_process_builder.core.document import Document
from gemseo_process_builder.core.model import Link
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.quick_fixes import fix_command
from gemseo_process_builder.core.resolver import level_view
from gemseo_process_builder.core.resolver import resolve
from gemseo_process_builder.core.validation import Problem
from gemseo_process_builder.core.validation import ValidationContext
from gemseo_process_builder.core.validation import validate


def problems(p: Project) -> list[Problem]:
    context = ValidationContext(p, resolve(p), options={"show_unused_outputs": False})
    return validate(context)


def codes(p: Project) -> list[str]:
    return [problem.code for problem in problems(p)]


def port(name: str, direction: str, **fields: Any) -> Port:
    return Port(local_name=name, direction=direction, default=1.0, **fields)  # type: ignore[arg-type]


def chain(out_unit: str | None, in_unit: str | None) -> Project:
    source = component("Source")
    source.ports = [port("t", "out", unit=out_unit)]
    use = component("Use")
    use.ports = [port("t", "in", unit=in_unit)]
    return project(source, use)


def test_same_units_are_clean() -> None:
    assert codes(chain("m", "m")) == []


def test_invalid_unit() -> None:
    assert codes(chain("bogus", "m")) == ["invalid_unit"]


def test_incompatible_units() -> None:
    (problem,) = problems(chain("m", "s"))
    assert problem.code == "incompatible_units"
    assert problem.level == "error"
    assert (problem.node, problem.port) == ("n-Use", "t")


def test_converted_units_warn() -> None:
    (problem,) = problems(chain("mm", "m"))
    assert problem.code == "unit_conversion"
    assert "mm → m, × 0.001" in problem.message


def test_missing_unit_informs() -> None:
    assert codes(chain(None, "m")) == ["unit_missing"]


def test_disabled_conversion_can_be_enabled_again() -> None:
    p = chain("mm", "m")
    use = p.find("n-Use")
    use.ports[0] = use.ports[0].model_copy(update={"convert_units": False})  # type: ignore[union-attr]
    (problem,) = problems(p)
    assert problem.code == "unit_not_converted"
    command = fix_command(problem, "enable_conversion")
    assert command is not None
    Document(p).execute(command)
    assert codes(p) == ["unit_conversion"]


def test_explicit_links_have_their_own_option() -> None:
    p = chain("mm", "m")
    p.links.append(
        Link(
            id="l-t",
            source={"node": "n-Source", "port": "t"},
            target={"node": "n-Use", "port": "t"},
            convert_units=False,
        )
    )
    (problem,) = problems(p)
    assert (problem.code, problem.link) == ("unit_not_converted", "l-t")
    Document(p).execute(
        parse_command({"type": "setLinkOptions", "id": "l-t", "convert_units": True})
    )
    assert codes(p) == ["unit_conversion"]


def test_level_view_carries_the_unit_check() -> None:
    p = chain("mm", "m")
    (edge,) = level_view(resolve(p), p, "n-root")["edges"]
    (variable,) = edge["variables"]
    assert variable["unit"]["status"] == "convert"
    assert variable["unit"]["factor"] == 0.001
    assert variable["converted"] is True


def test_integer_feeding_float_informs() -> None:
    p = chain(None, None)
    source = p.find("n-Source")
    source.ports[0] = source.ports[0].model_copy(update={"dtype": "int"})  # type: ignore[union-attr]
    assert codes(p) == ["int_to_float"]


def loop(shape: list[int], dtype: str = "float") -> Project:
    a = component("A")
    a.ports = [
        port("m", "out", shape=shape, dtype=dtype),
        port("n", "in", shape=shape, dtype=dtype),
    ]
    b = component("B")
    b.ports = [
        port("m", "in", shape=shape, dtype=dtype),
        port("n", "out", shape=shape, dtype=dtype),
    ]
    return project(a, b)


def test_matrices_solved_by_an_mda() -> None:
    p = loop([2, 2])
    found = [problem for problem in problems(p) if problem.code == "nd_mda_coupling"]
    assert {(problem.node, problem.port) for problem in found} == {
        ("n-A", "m"),
        ("n-B", "n"),
    }
    Document(p).execute(fix_command(found[0], "accept_flattening"))  # type: ignore[arg-type]
    assert codes(p).count("nd_mda_coupling") == 1
    assert codes(loop([4])) == []


def test_text_cannot_be_solved_by_an_mda() -> None:
    assert codes(loop([], "str")).count("text_mda_coupling") == 2


def test_matrix_design_variable() -> None:
    model = component("Model")
    model.ports = [port("p", "in", shape=[2, 2]), port("f", "out")]
    study = driver(
        "Study",
        "optimization",
        model,
        config={
            "design_space": [{"variable": "p", "size": 4}],
            "objectives": [{"variable": "f"}],
        },
    )
    p = project(study)
    (problem,) = [
        problem for problem in problems(p) if problem.code == "nd_design_variable"
    ]
    assert (problem.node, problem.port) == ("n-Model", "p")
    Document(p).execute(fix_command(problem, "accept_flattening"))  # type: ignore[arg-type]
    assert "nd_design_variable" not in codes(p)
