// @ts-check
// The table of the variables of a discipline class written by the application
// (`core/discipline_file.py` does the same checks before writing). Inputs are
// NumPy arrays of any shape and of type float, int or complex; their default
// value is one number filling them, or every element. Pure: no DOM.

/**
 * @typedef {object} TableVariable
 * @property {string} name
 * @property {"in" | "out"} direction
 * @property {"float" | "int" | "complex"} [dtype]
 * @property {number[]} [shape] - Like [3] or [3, 4].
 * @property {number[] | null} [values] - Every element of the default value.
 * @property {number | null} [fill] - One value for every element.
 */

/** Values typed one by one at most; larger arrays are filled with one value. */
export const MAX_VALUES = 20;

const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** Python keywords, which cannot be variable names. */
const KEYWORDS = new Set(
  (
    "False None True and as assert async await break class continue def del elif else except finally for from global " +
    "if import in is lambda nonlocal not or pass raise return try while with yield"
  ).split(" "),
);

/**
 * A shape typed as "100000", "100_000", "3x4", "3×4" or "(3, 4)".
 *
 * @param {string} text
 * @returns {{value: number[] | null, error: string}}
 */
export function parseShape(text) {
  const parts = text
    .replace(/[()]/g, "")
    .split(/[x×*,;\s]+/)
    .filter(Boolean)
    .map((part) => Number(part.replaceAll("_", "")));
  if (!parts.length || parts.some((size) => !Number.isInteger(size) || size < 1)) {
    return { value: null, error: "Enter sizes like 3, 100000 or 3x4." };
  }
  return { value: parts, error: "" };
}

/**
 * The text of a shape: "3", "3×4".
 *
 * @param {number[] | undefined} shape
 */
export function formatShape(shape) {
  return (shape ?? [1]).join("×");
}

/** @param {number[] | undefined} shape */
function sizeOf(shape) {
  return (shape ?? [1]).reduce((product, size) => product * size, 1);
}

/**
 * A default value typed as "0.5" (filling the array) or "1, 2, 3" (every element).
 *
 * @param {string} text
 * @param {number[]} [shape]
 * @returns {{values: number[] | null, fill: number | null, error: string}}
 */
export function parseDefault(text, shape = [1]) {
  const parts = text.split(/[\s,;]+/).filter(Boolean);
  if (!parts.length) {
    return { values: null, fill: null, error: "Give a default value." };
  }
  const numbers = parts.map(Number);
  if (numbers.some((value) => !Number.isFinite(value))) {
    return { values: null, fill: null, error: "Enter numbers separated by commas." };
  }
  if (numbers.length === 1) {
    return { values: null, fill: numbers[0], error: "" };
  }
  const size = sizeOf(shape);
  if (numbers.length > MAX_VALUES) {
    return { values: null, fill: null, error: `At most ${MAX_VALUES} values: give one value filling the array.` };
  }
  if (numbers.length !== size) {
    return { values: null, fill: null, error: `${numbers.length} values for ${size} elements: give one, or one per element.` };
  }
  return { values: numbers, fill: null, error: "" };
}

/**
 * The text of a default value.
 *
 * @param {TableVariable} variable
 */
export function formatDefault(variable) {
  if (variable.values) {
    return variable.values.join(", ");
  }
  return variable.fill === null || variable.fill === undefined ? "" : String(variable.fill);
}

/**
 * What is wrong with the variables, one message per problem.
 *
 * @param {TableVariable[]} variables
 * @returns {string[]}
 */
export function checkVariables(variables) {
  const errors = [];
  const seen = new Set();
  for (const variable of variables) {
    if (!NAME.test(variable.name) || KEYWORDS.has(variable.name)) {
      errors.push(`"${variable.name}" is not a valid Python name: use letters, digits and _.`);
    } else if (seen.has(variable.name)) {
      errors.push(`${variable.name} is declared twice.`);
    }
    seen.add(variable.name);
    if (variable.direction !== "in") {
      continue;
    }
    if (!variable.values?.length && (variable.fill === null || variable.fill === undefined)) {
      errors.push(`Give a default value to the input ${variable.name}.`);
    } else if (variable.values && variable.values.length !== sizeOf(variable.shape)) {
      errors.push(`${variable.name} has ${variable.values.length} values for ${sizeOf(variable.shape)} elements.`);
    }
  }
  if (!variables.some((variable) => variable.direction === "out")) {
    errors.push("Add at least one output.");
  }
  return errors;
}

/**
 * A class name from a component name: "my wing 2" gives "MyWing2".
 *
 * @param {string} name
 */
export function classNameFor(name) {
  const text = (name.match(/[A-Za-z0-9]+/g) ?? []).map((word) => word[0].toUpperCase() + word.slice(1)).join("");
  return !text || /^[0-9]/.test(text) ? `Discipline${text}` : text;
}

/**
 * A module file name from a class name: "WingArea" gives "wing_area.py".
 *
 * @param {string} className
 */
export function fileNameFor(className) {
  return `${className.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase()}.py`;
}

/**
 * A name not used yet: "x", then "x_2", "x_3"…
 *
 * @param {string} base
 * @param {TableVariable[]} variables
 */
export function freeName(base, variables) {
  const used = new Set(variables.map((variable) => variable.name));
  if (!used.has(base)) {
    return base;
  }
  let index = 2;
  while (used.has(`${base}_${index}`)) {
    index += 1;
  }
  return `${base}_${index}`;
}
