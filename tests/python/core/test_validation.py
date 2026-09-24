from builders import assembly
from builders import component
from builders import project

from gemseo_process_builder.core.document import Document
from gemseo_process_builder.core.model import Link
from gemseo_process_builder.core.model import Port
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.quick_fixes import fix_command
from gemseo_process_builder.core.resolver import resolve
from gemseo_process_builder.core.validation import Problem
from gemseo_process_builder.core.validation import ValidationContext
from gemseo_process_builder.core.validation import validate


def problems(
    p: Project, errors: dict[str, str] | None = None, unused: bool = False
) -> list[Problem]:
    context = ValidationContext(
        p, resolve(p), errors or {}, {"show_unused_outputs": unused}
    )
    return validate(context)


def codes(p: Project, **options: object) -> list[str]:
    return [problem.code for problem in problems(p, **options)]  # type: ignore[arg-type]


def with_default(node: object, port: str, value: float) -> None:
    for candidate in node.ports:  # type: ignore[attr-defined]
        if candidate.local_name == port:
            candidate.default = value


def test_clean_model() -> None:
    a = component("A", ins=["x"], outs=["y"])
    with_default(a, "x", 1.0)
    assert codes(project(a, component("B", ins=["y"]))) == []


def test_duplicate_producer_with_isolation_fix() -> None:
    p = project(component("A", outs=["y"]), component("B", outs=["y"]))
    (problem,) = problems(p)
    assert (problem.code, problem.level, problem.node) == (
        "duplicate_producer",
        "error",
        "n-B",
    )
    document = Document(p)
    command = fix_command(problem, "isolate_namespace")
    assert command is not None
    document.execute(command)
    assert codes(p) == []
    document.undo()
    assert codes(p) == ["duplicate_producer"]


def test_multiple_links_fix_removes_the_extra_link() -> None:
    p = project(
        component("A", outs=["a"]),
        component("B", outs=["b"]),
        component("C", ins=["x"]),
    )
    for link_id, source, output in (("l-1", "n-A", "a"), ("l-2", "n-B", "b")):
        p.links.append(
            Link(
                id=link_id,
                source={"node": source, "port": output},
                target={"node": "n-C", "port": "x"},
            )
        )
    (problem,) = [p_ for p_ in problems(p) if p_.code == "multiple_explicit_links"]
    Document(p).execute(fix_command(problem, "remove_link"))  # type: ignore[arg-type]
    assert [link.id for link in p.links] == ["l-1"]


def test_incompatible_coupling() -> None:
    a = component("A", outs=["y"])
    a.ports[0] = Port(local_name="y", direction="out", dtype="str")
    assert "incompatible_coupling" in codes(project(a, component("B", ins=["y"])))
    sized = component("C", outs=["v"])
    sized.ports[0] = Port(local_name="v", direction="out", shape=[3])
    target = component("D", ins=["v"])
    target.ports[0] = Port(local_name="v", direction="in", shape=[2])
    assert "incompatible_coupling" in codes(project(sized, target))


def test_loop_in_chain_fix_switches_to_mda() -> None:
    group = assembly(
        "G",
        component("A", ins=["b"], outs=["a"]),
        component("B", ins=["a"], outs=["b"]),
        mode="chain",
    )
    p = project(group)
    (problem,) = [p_ for p_ in problems(p) if p_.code == "loop_in_chain"]
    Document(p).execute(fix_command(problem, "switch_to_mda"))  # type: ignore[arg-type]
    assert group.mode == "mda"
    assert "loop_in_chain" not in codes(p)


def test_introspection_errors_and_missing_ports() -> None:
    a = component("A", outs=["y"])
    a.ports[0] = Port(local_name="y", direction="out", missing=True)
    (problem,) = problems(project(a), {"n-A": "ImportError: nope"})[:1]
    assert problem.code == "introspection_failed"
    assert problem.quick_fixes == ["reintrospect"]
    assert fix_command(problem, "reintrospect") is None
    assert "missing_port" in codes(project(a))


def test_free_input_without_default_is_a_warning() -> None:
    (problem,) = problems(project(component("A", ins=["x"])))
    assert (problem.code, problem.level, problem.port) == (
        "free_input_without_default",
        "warning",
        "x",
    )


def test_unused_outputs_are_optional_information() -> None:
    p = project(component("A", outs=["y"]))
    assert codes(p) == []
    (problem,) = problems(p, unused=True)
    assert (problem.code, problem.level) == ("unused_output", "info")


def test_problems_are_sorted_and_keys_are_stable() -> None:
    p = project(
        component("A", ins=["x"], outs=["y"]),
        component("B", outs=["y"]),
    )
    first = [problem.key for problem in problems(p)]
    assert [problem.level for problem in problems(p)] == ["error", "warning"]
    p.root.children.append(component("C", ins=[]))
    assert [problem.key for problem in problems(p)] == first
