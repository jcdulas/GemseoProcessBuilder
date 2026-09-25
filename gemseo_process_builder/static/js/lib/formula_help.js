// @ts-check
// Help to type the formulas of an Analytic component: the functions SymPy
// knows, examples, the inputs and outputs a set of formulas defines, the names
// SymPy reserves, and the completion of the word being typed. Pure: no DOM.

/** @typedef {{name: string, insert: string, help: string}} FormulaFunction */

/** @type {FormulaFunction[]} */
export const FORMULA_FUNCTIONS = [
  { name: "sqrt", insert: "sqrt()", help: "square root" },
  { name: "exp", insert: "exp()", help: "exponential" },
  { name: "log", insert: "log()", help: "natural logarithm; log(x, 10) in base 10" },
  { name: "sin", insert: "sin()", help: "sine, in radians" },
  { name: "cos", insert: "cos()", help: "cosine, in radians" },
  { name: "tan", insert: "tan()", help: "tangent, in radians" },
  { name: "asin", insert: "asin()", help: "arc sine" },
  { name: "acos", insert: "acos()", help: "arc cosine" },
  { name: "atan", insert: "atan()", help: "arc tangent" },
  { name: "atan2", insert: "atan2(, )", help: "angle of the point (x, y): atan2(y, x)" },
  { name: "sinh", insert: "sinh()", help: "hyperbolic sine" },
  { name: "cosh", insert: "cosh()", help: "hyperbolic cosine" },
  { name: "tanh", insert: "tanh()", help: "hyperbolic tangent" },
  { name: "Abs", insert: "Abs()", help: "absolute value (with a capital A)" },
  { name: "Min", insert: "Min(, )", help: "the smallest of its arguments (with a capital M)" },
  { name: "Max", insert: "Max(, )", help: "the largest of its arguments (with a capital M)" },
  { name: "sign", insert: "sign()", help: "-1, 0 or 1" },
];

export const FORMULA_OPERATORS = [
  { text: "+ - * /", help: "add, subtract, multiply, divide" },
  { text: "**", help: "power: x**2 (not x^2)" },
  { text: "( )", help: "group: (a + b)/2" },
  { text: "pi", help: "the number π" },
];

export const FORMULA_EXAMPLES = [
  { text: "y = 2*x + 1", help: "a straight line" },
  { text: "area = pi*radius**2", help: "a constant" },
  { text: "f = (1 - x)**2 + 100*(y - x**2)**2", help: "the Rosenbrock function" },
  { text: "stress = force/area", help: "a physical relation" },
  { text: "g = sqrt(x**2 + y**2) - 1", help: "a constraint, feasible when g <= 0" },
];

/** The constants SymPy gives a value to, allowed in formulas. */
export const CONSTANTS = new Set(["pi"]);

/**
 * Names users often give to variables, which SymPy reads as something else.
 * The worker checks every name against SymPy; these ones are flagged while
 * typing.
 */
export const RESERVED_NAMES = new Set([
  "E", "I", "N", "O", "Q", "S", "oo", "nan", "zoo",
  "beta", "gamma", "zeta", "lambda", "re", "im", "ln", "li", "Li", "Ei", "erf",
  "sign", "floor", "ceiling", "diff", "test", "rf", "ff", "LT", "GT", "Lambda",
  "sin", "cos", "tan", "exp", "log", "sqrt", "Abs", "Min", "Max",
]);

const IDENTIFIER = /[A-Za-z_][A-Za-z0-9_]*/g;

/**
 * The names a set of formulas uses.
 *
 * @param {Record<string, string>} expressions - Output name → formula.
 * @returns {{inputs: string[], outputs: string[], functions: string[], reserved: string[]}}
 *   The inputs are the names used as variables that are not outputs nor
 *   constants; ``reserved`` lists the names SymPy would misread.
 */
export function formulaSymbols(expressions) {
  const outputs = Object.keys(expressions);
  const inputs = new Set();
  const functions = new Set();
  const reserved = new Set(outputs.filter((name) => RESERVED_NAMES.has(name)));
  for (const formula of Object.values(expressions)) {
    for (const match of formula.matchAll(IDENTIFIER)) {
      const name = match[0];
      const index = /** @type {number} */ (match.index);
      // A number like 1e5 contains an identifier-looking "e5".
      if (index > 0 && /[0-9.]/.test(formula[index - 1])) {
        continue;
      }
      const called = /^\s*\(/.test(formula.slice(index + name.length));
      if (called) {
        functions.add(name);
      } else if (RESERVED_NAMES.has(name)) {
        reserved.add(name);
      } else if (!CONSTANTS.has(name) && !outputs.includes(name)) {
        inputs.add(name);
      }
    }
  }
  return { inputs: [...inputs].sort(), outputs, functions: [...functions].sort(), reserved: [...reserved].sort() };
}

/**
 * The word being typed at a position of a text, if any.
 *
 * @param {string} text
 * @param {number} caret
 * @returns {{word: string, start: number, end: number} | null}
 */
export function wordAt(text, caret) {
  let start = caret;
  while (start > 0 && /[A-Za-z0-9_]/.test(text[start - 1])) {
    start -= 1;
  }
  let end = caret;
  while (end < text.length && /[A-Za-z0-9_]/.test(text[end])) {
    end += 1;
  }
  const word = text.slice(start, end);
  return /^[A-Za-z_]/.test(word) ? { word, start, end } : null;
}

/**
 * The names completing a word: the variables first, then the functions.
 *
 * @param {string} word
 * @param {string[]} variables - Names known in the model.
 * @param {number} [limit]
 * @returns {{name: string, insert: string, help: string}[]}
 */
export function completions(word, variables, limit = 8) {
  const lower = word.toLowerCase();
  const matches = (/** @type {string} */ name) => name.toLowerCase().startsWith(lower) && name !== word;
  return [
    ...variables.filter(matches).map((name) => ({ name, insert: name, help: "a variable of the model" })),
    ...FORMULA_FUNCTIONS.filter((item) => matches(item.name)),
  ].slice(0, limit);
}

/**
 * Replace the word being typed by a completion; the caret goes inside the
 * parentheses of a function.
 *
 * @param {string} text
 * @param {{start: number, end: number}} word
 * @param {string} insert
 * @returns {{text: string, caret: number}}
 */
export function complete(text, word, insert) {
  const next = text.slice(0, word.start) + insert + text.slice(word.end);
  const parenthesis = insert.indexOf("(");
  const caret = word.start + (parenthesis >= 0 ? parenthesis + 1 : insert.length);
  return { text: next, caret };
}
