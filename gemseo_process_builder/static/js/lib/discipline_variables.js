// @ts-check
// The table of the variables of a discipline class written by the application
// (`core/discipline_file.py` does the same checks before writing). Pure: no DOM.

/**
 * @typedef {object} TableVariable
 * @property {string} name
 * @property {"in" | "out"} direction
 * @property {number[] | null} default - The default value of an input, one number per element.
 */

const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** Python keywords, which cannot be variable names. */
const KEYWORDS = new Set(
  (
    "False None True and as assert async await break class continue def del elif else except finally for from global " +
    "if import in is lambda nonlocal not or pass raise return try while with yield"
  ).split(" "),
);

/**
 * A default value typed as "1.5" or "1, 2, 3".
 *
 * @param {string} text
 * @returns {{value: number[] | null, error: string}}
 */
export function parseDefault(text) {
  const parts = text.split(/[\s,;]+/).filter(Boolean);
  if (!parts.length) {
    return { value: null, error: "Give a default value." };
  }
  const values = parts.map(Number);
  return values.some((value) => !Number.isFinite(value))
    ? { value: null, error: "Enter numbers separated by commas." }
    : { value: values, error: "" };
}

/**
 * The text of a default value.
 *
 * @param {number[] | null | undefined} values
 */
export function formatDefault(values) {
  return (values ?? []).join(", ");
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
    if (variable.direction === "in" && !variable.default?.length) {
      errors.push(`Give a default value to the input ${variable.name}.`);
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
