"""Naming, literals, expression layout and module assembly."""

import pytest

from gemseo_process_builder.codegen.literals import literal
from gemseo_process_builder.codegen.naming import NameAllocator
from gemseo_process_builder.codegen.naming import to_identifier
from gemseo_process_builder.codegen.pretty import Call
from gemseo_process_builder.codegen.pretty import DictExpr
from gemseo_process_builder.codegen.pretty import ListExpr
from gemseo_process_builder.codegen.pretty import Raw
from gemseo_process_builder.codegen.pretty import flat
from gemseo_process_builder.codegen.pretty import render
from gemseo_process_builder.codegen.pretty import statement
from gemseo_process_builder.codegen.pretty import string
from gemseo_process_builder.codegen.writer import Function
from gemseo_process_builder.codegen.writer import ModuleWriter


@pytest.mark.parametrize(
    ("name", "identifier"),
    [
        ("SellarSystem", "sellar_system"),
        ("MDA2_Wing", "mda2_wing"),
        ("HTTPServer", "http_server"),
        ("Aile avant (été)", "aile_avant_ete"),
        ("2nd stage", "node_2nd_stage"),
        ("***", "node"),
    ],
)
def test_to_identifier(name: str, identifier: str) -> None:
    assert to_identifier(name) == identifier


def test_name_allocator_avoids_collisions_and_reserved_words() -> None:
    names = NameAllocator({"main"})
    assert [names.allocate(base) for base in ("wing", "wing", "wing")] == [
        "wing",
        "wing_2",
        "wing_3",
    ]
    assert names.allocate("class") == "class_2"
    assert names.allocate("list") == "list_2"
    assert names.allocate("main") == "main_2"


@pytest.mark.parametrize(
    ("value", "text", "code"),
    [
        (1e-6, "1e-6", "1e-6"),
        (1e-6, "1E-6", "1e-6"),
        (1e-6, None, "1e-06"),
        (2, "abc", "2"),
        (float("inf"), None, 'float("inf")'),
        (True, None, "True"),
        (None, None, "None"),
        ('a"b', None, '"a\\"b"'),
        ([1, 2.5], None, "[1, 2.5]"),
        ({"a": {"b": [1]}}, None, '{"a": {"b": [1]}}'),
    ],
)
def test_literal(value: object, text: str | None, code: str) -> None:
    assert flat(literal(value, text)) == code


def test_literal_refuses_other_types() -> None:
    with pytest.raises(TypeError, match="set"):
        literal({1})


def test_render_keeps_short_expressions_on_one_line() -> None:
    call = Call("f", [("", Raw("x")), ("name", string("A"))])
    assert statement("y", call) == ['    y = f(x, name="A")']


def test_render_moves_arguments_to_one_indented_line() -> None:
    call = Call("function", [("", Raw("a" * 40)), ("", Raw("b" * 40))])
    assert render(call, "result = ") == [
        "result = function(",
        f"    {'a' * 40}, {'b' * 40}",
        ")",
    ]


def test_render_puts_one_element_per_line_with_a_trailing_comma() -> None:
    items = DictExpr(
        [(string(f"key_{i}"), ListExpr([Raw("1.0")] * 3)) for i in range(5)]
    )
    lines = render(Call("f", [("mapping", items)]), indent="    ")
    assert lines[0] == "    f("
    assert lines[1] == "        mapping={"
    assert lines[2] == '            "key_0": [1.0, 1.0, 1.0],'
    assert lines[-2:] == ["        },", "    )"]
    assert all(len(line) <= 88 for line in lines)


def test_module_writer_groups_imports_by_section() -> None:
    writer = ModuleWriter("Title.")
    writer.use("gemseo", "create_mda")
    writer.use("gemseo", "Discipline")
    writer.use("pathlib", "Path")
    writer.use_module("sys")
    writer.use("gemseo_process_builder.runtime", "component")
    writer.constants.append('FOLDER = Path("a")')
    writer.functions.append(Function("def main() -> None:", "Run.", ["    pass"]))
    assert writer.source().splitlines() == [
        '"""Title.',
        '"""',
        "",
        "import sys",
        "from pathlib import Path",
        "",
        "from gemseo import Discipline, create_mda",
        "",
        "from gemseo_process_builder.runtime import component",
        "",
        'FOLDER = Path("a")',
        "",
        "",
        "def main() -> None:",
        '    """Run."""',
        "    pass",
        "",
        "",
        'if __name__ == "__main__":',
        "    main()",
    ]


def test_module_writer_wraps_long_imports() -> None:
    writer = ModuleWriter("Title.")
    for index in range(12):
        writer.use("package.module", f"function_{index:02d}")
    lines = writer.source().splitlines()
    assert lines[3] == "from package.module import ("
    assert lines[4] == "    function_00,"
