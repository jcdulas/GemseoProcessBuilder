// @ts-check
// Whether an output can feed an input: type and shape here; units are checked
// by Python (pint), whose answer ``unitCompatibility`` turns into feedback.

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

/**
 * Feedback on the units of a link, from Python's check (``units.check``).
 *
 * @param {{status: string, message: string} | null | undefined} check
 * @returns {{ok: boolean, warning: string, reason: string}}
 */
export function unitCompatibility(check) {
  if (!check) {
    return { ok: true, warning: "", reason: "" };
  }
  if (check.status === "incompatible") {
    return { ok: false, warning: "", reason: `The units differ: ${check.message}.` };
  }
  if (check.status === "convert") {
    return { ok: true, warning: `The value will be converted (${check.message}).`, reason: "" };
  }
  if (check.status === "invalid") {
    return { ok: true, warning: `${check.message}`, reason: "" };
  }
  return { ok: true, warning: "", reason: "" };
}

/**
 * The text describing the unit conversions of the variables of a link.
 *
 * @param {{name: string, unit?: {status: string, message: string}, converted?: boolean}[]} variables
 * @returns {string[]}
 */
export function conversionNotes(variables) {
  return variables
    .filter((variable) => variable.unit?.status === "convert")
    .map((variable) => `${variable.name}: ${variable.unit?.message}${variable.converted ? "" : " (not converted)"}`);
}

/** @param {number[] | undefined} shape */
function isScalarLike(shape) {
  return !shape || shape.length === 0 || (shape.length === 1 && shape[0] === 1);
}

/** @param {number[] | undefined} shape */
function describe(shape) {
  return !shape || shape.length === 0 ? "scalar" : shape.join("×");
}
