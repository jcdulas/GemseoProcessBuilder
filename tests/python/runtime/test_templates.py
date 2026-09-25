import numpy as np
import pytest

from gemseo_process_builder.runtime.templates import TemplateError
from gemseo_process_builder.runtime.templates import format_value
from gemseo_process_builder.runtime.templates import markers
from gemseo_process_builder.runtime.templates import render


def test_scalars_with_and_without_format() -> None:
    template = "x = {{x}}\nthickness = {{ t:.3e }}\n"
    text = render(template, {"x": 1.5, "t": np.array([0.0025])})
    assert text == "x = 1.5\nthickness = 2.500e-03\n"


def test_vectors_are_joined() -> None:
    values = {"v": np.array([1.0, 2.5, 3.0])}
    assert render("{{v:.1f}}", values) == "1.0 2.5 3.0"
    assert render("{{v:.1f}}", values, separator="\n") == "1.0\n2.5\n3.0"
    assert format_value([[1, 2], [3, 4]]) == "1 2 3 4"


def test_markers_in_order_without_repetitions() -> None:
    assert markers("{{b}} {{a:.2f}} {{b}} \\{{c}}") == ["b", "a"]


def test_escaped_markers_are_written_as_they_are() -> None:
    assert render("\\{{x}} is {{x}}", {"x": 2}) == "{{x}} is 2"


def test_missing_input() -> None:
    with pytest.raises(TemplateError, match=r"uses \{\{y\}\}, which is not an input"):
        render("{{y}}", {"x": 1.0})


def test_bad_format() -> None:
    with pytest.raises(TemplateError, match="does not apply"):
        render("{{x:.3q}}", {"x": 1.0})
