// @ts-check
// Whether an output can feed an input (type and shape; units come later).

const TEXT_TYPES = new Set(["str", "path"]);
const NUMBER_TYPES = new Set(["float", "int", "complex"]);

/**
 * @typedef {object} PortInfo
 * @property {string} [dtype]
 * @property {number[]} [shape]
 * @property {boolean} [shape_known]
 */

/**
 * @param {PortInfo} output
 * @param {PortInfo} input
 * @returns {{ok: boolean, warning: string, reason: string}}
 */
export function linkCompatibility(output, input) {
  const outType = output.dtype ?? "float";
  const inType = input.dtype ?? "float";
  if (outType !== "object" && inType !== "object") {
    if (TEXT_TYPES.has(outType) !== TEXT_TYPES.has(inType)) {
      return { ok: false, warning: "", reason: `A ${outType} value cannot feed a ${inType} variable.` };
    }
    if (NUMBER_TYPES.has(outType) && NUMBER_TYPES.has(inType)) {
      if (outType === "complex" && inType !== "complex") {
        return { ok: false, warning: "", reason: `A complex value cannot feed a ${inType} variable.` };
      }
      if (outType === "float" && inType === "int") {
        return { ok: false, warning: "", reason: "A float value cannot feed an integer variable." };
      }
    }
  }
  const outKnown = output.shape_known !== false;
  const inKnown = input.shape_known !== false;
  if (outKnown && inKnown) {
    const outShape = JSON.stringify(output.shape ?? []);
    const inShape = JSON.stringify(input.shape ?? []);
    if (outShape !== inShape && !(isScalarLike(output.shape) && isScalarLike(input.shape))) {
      return { ok: false, warning: "", reason: `The sizes differ (${describe(output.shape)} and ${describe(input.shape)}).` };
    }
    return { ok: true, warning: "", reason: "" };
  }
  return { ok: true, warning: "The size of one variable is unknown until it runs.", reason: "" };
}

/** @param {number[] | undefined} shape */
function isScalarLike(shape) {
  return !shape || shape.length === 0 || (shape.length === 1 && shape[0] === 1);
}

/** @param {number[] | undefined} shape */
function describe(shape) {
  return !shape || shape.length === 0 ? "scalar" : shape.join("×");
}
