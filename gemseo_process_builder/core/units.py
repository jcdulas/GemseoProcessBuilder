"""Physical units of the variables (SPEC § 5.5), with pint.

A unit is a pint string: ``""`` for dimensionless, ``None`` when unknown. The
check of a coupling says whether values pass as they are, need a conversion
(``target = factor * source + offset``, affine for temperatures), cannot pass
(different dimensions), or cannot be checked (a unit is missing or invalid).

pint is pure Python: this module runs in the UI process. Its registry is slow
to create, so it is created once, on first use.
"""

from dataclasses import dataclass
from functools import cache
from typing import Any
from typing import Literal

UnitStatus = Literal["same", "convert", "incompatible", "missing", "invalid"]

COMMON_UNITS = (
    "",
    "m",
    "mm",
    "cm",
    "km",
    "ft",
    "inch",
    "m**2",
    "m**3",
    "kg",
    "g",
    "lb",
    "s",
    "min",
    "h",
    "N",
    "kN",
    "Pa",
    "kPa",
    "MPa",
    "bar",
    "J",
    "kJ",
    "W",
    "kW",
    "K",
    "degC",
    "degF",
    "rad",
    "deg",
    "m/s",
    "km/h",
    "kg/m**3",
)
"""Units offered while typing (any pint unit is accepted)."""


class UnitError(ValueError):
    """A string that is not a unit."""


@cache
def registry() -> Any:
    """The pint registry of the process."""
    import pint

    return pint.UnitRegistry(autoconvert_offset_to_baseunit=True)


def parse(text: str) -> Any:
    """The pint unit of a string.

    Raises:
        UnitError: When the string is not a unit.
    """
    if not text.strip():
        return registry().dimensionless
    try:
        return registry().parse_units(text.strip())
    except Exception as error:  # pint raises several kinds of errors.
        msg = f"{text!r} is not a unit."
        raise UnitError(msg) from error


def is_valid(text: str | None) -> bool:
    """Whether a unit string is valid (``None``, unknown, is valid)."""
    if text is None:
        return True
    try:
        parse(text)
    except UnitError:
        return False
    return True


@dataclass(frozen=True)
class UnitCheck:
    """How a value in one unit feeds a variable in another."""

    status: UnitStatus
    factor: float = 1.0
    offset: float = 0.0
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """The check as sent to the page."""
        return {
            "status": self.status,
            "factor": self.factor,
            "offset": self.offset,
            "message": self.message,
        }


def _label(text: str) -> str:
    return text.strip() or "dimensionless"


def conversion_text(source: str, target: str, factor: float, offset: float) -> str:
    """Like ``mm → m, × 0.001`` or ``degC → K, + 273.15``."""
    parts = []
    if factor != 1:
        parts.append(f"× {factor:.6g}")
    if offset:
        parts.append(f"{'−' if offset < 0 else '+'} {abs(offset):.6g}")
    return f"{_label(source)} → {_label(target)}, {' '.join(parts) or 'same values'}"


@cache
def check(source: str | None, target: str | None) -> UnitCheck:
    """How an output in unit ``source`` feeds an input in unit ``target``."""
    if source is None or target is None:
        if source is None and target is None:
            return UnitCheck("same")
        known = str(target if source is None else source)
        side = "output" if source is None else "input"
        return UnitCheck(
            "missing",
            message=f"the unit of the {side} is not given ({_label(known)} on the "
            "other side)",
        )
    try:
        source_unit = parse(source)
        target_unit = parse(target)
    except UnitError as error:
        return UnitCheck("invalid", message=str(error))
    if source_unit == target_unit:
        return UnitCheck("same")
    if source_unit.dimensionality != target_unit.dimensionality:
        return UnitCheck(
            "incompatible",
            message=f"{_label(source)} cannot be converted to {_label(target)}",
        )
    quantity = registry().Quantity
    offset = float(quantity(0.0, source_unit).to(target_unit).magnitude)
    factor = float(quantity(1.0, source_unit).to(target_unit).magnitude) - offset
    # Round-off of the conversion (1e-3 * 1e3 is not exactly 1).
    factor = float(f"{factor:.12g}")
    offset = float(f"{offset:.12g}")
    return UnitCheck(
        "convert",
        factor=factor,
        offset=offset,
        message=conversion_text(source, target, factor, offset),
    )


def suggestions(prefix: str, limit: int = 10) -> list[str]:
    """Common units starting with what is typed."""
    return [unit for unit in COMMON_UNITS if unit and unit.startswith(prefix)][:limit]
