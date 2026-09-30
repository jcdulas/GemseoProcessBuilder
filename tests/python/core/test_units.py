import pytest

from gemseo_process_builder.core.units import UnitError
from gemseo_process_builder.core.units import check
from gemseo_process_builder.core.units import is_valid
from gemseo_process_builder.core.units import parse
from gemseo_process_builder.core.units import suggestions


def test_same_units_pass_as_they_are() -> None:
    assert check("m", "m").status == "same"
    assert check("", "").status == "same"
    assert check("N*m", "J").status == "convert"  # Same dimension, other unit.
    assert check(None, None).status == "same"


@pytest.mark.parametrize(
    ("source", "target", "factor", "offset", "message"),
    [
        ("mm", "m", 0.001, 0.0, "mm → m, × 0.001"),
        ("kN", "N", 1000.0, 0.0, "kN → N, × 1000"),
        ("degC", "K", 1.0, 273.15, "degC → K, + 273.15"),
        ("K", "degC", 1.0, -273.15, "K → degC, − 273.15"),
        ("m/s", "km/h", 3.6, 0.0, "m/s → km/h, × 3.6"),
    ],
)
def test_conversions(
    source: str, target: str, factor: float, offset: float, message: str
) -> None:
    result = check(source, target)
    assert result.status == "convert"
    assert result.factor == pytest.approx(factor)
    assert result.offset == pytest.approx(offset)
    assert result.message == message


def test_degrees_fahrenheit_are_affine() -> None:
    result = check("degF", "degC")
    assert 212 * result.factor + result.offset == pytest.approx(100.0)


def test_incompatible_dimensions() -> None:
    result = check("m", "s")
    assert result.status == "incompatible"
    assert result.message == "m cannot be converted to s"
    assert check("", "m").status == "incompatible"


def test_missing_and_invalid_units() -> None:
    assert check(None, "m").message == (
        "the unit of the output is not given (m on the other side)"
    )
    assert check("mm", None).status == "missing"
    assert check("bogus", "m").status == "invalid"
    assert not is_valid("bogus")
    assert is_valid(None)
    assert is_valid("")
    with pytest.raises(UnitError, match="is not a unit"):
        parse("m**")


def test_suggestions() -> None:
    assert suggestions("k") == ["km", "kg", "kN", "kPa", "kJ", "kW", "km/h", "kg/m**3"]
    assert "" not in suggestions("")
