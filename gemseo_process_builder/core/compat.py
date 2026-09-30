"""Whether an output can feed an input.

The rules are the same as in ``static/js/lib/link_compat.js``.
"""

from gemseo_process_builder.core.model import Port

TEXT_TYPES = {"str", "path"}
NUMBER_TYPES = {"float", "int", "complex"}


def _scalar_like(shape: list[int]) -> bool:
    return not shape or shape == [1]


def _describe(shape: list[int]) -> str:
    return "scalar" if not shape else "x".join(str(size) for size in shape)


def incompatibility(output: Port, input_: Port) -> str:
    """Why an output cannot feed an input, or an empty string."""
    out_type, in_type = output.dtype, input_.dtype
    if "object" not in (out_type, in_type):
        if (out_type in TEXT_TYPES) != (in_type in TEXT_TYPES):
            return f"a {out_type} value cannot feed a {in_type} variable"
        if out_type == "complex" and in_type != "complex":
            return f"a complex value cannot feed a {in_type} variable"
        if out_type == "float" and in_type == "int":
            return "a float value cannot feed an integer variable"
    if (
        output.shape_known
        and input_.shape_known
        and output.shape != input_.shape
        and not (_scalar_like(output.shape) and _scalar_like(input_.shape))
    ):
        return (
            f"the sizes differ ({_describe(output.shape)} and "
            f"{_describe(input_.shape)})"
        )
    return ""
