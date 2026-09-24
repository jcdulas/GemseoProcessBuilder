// @ts-check
// Analytic expressions typed as "output = formula" lines.

const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;

/**
 * Parse lines like "y = x**2 + sin(z)"; blank lines and "#" comments are skipped.
 *
 * @param {string} text
 * @returns {{expressions: Record<string, string>, errors: string[]}}
 */
export function parseExpressionLines(text) {
  /** @type {Record<string, string>} */
  const expressions = {};
  const errors = [];
  for (const [index, raw] of text.split("\n").entries()) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }
    const equal = line.indexOf("=");
    if (equal < 0) {
      errors.push(`Line ${index + 1}: write "output = formula".`);
      continue;
    }
    const name = line.slice(0, equal).trim();
    const formula = line.slice(equal + 1).trim();
    if (!NAME.test(name)) {
      errors.push(`Line ${index + 1}: "${name}" is not a valid output name.`);
    } else if (!formula) {
      errors.push(`Line ${index + 1}: the formula of ${name} is empty.`);
    } else if (name in expressions) {
      errors.push(`Line ${index + 1}: ${name} is defined twice.`);
    } else {
      expressions[name] = formula;
    }
  }
  return { expressions, errors };
}

/**
 * @param {Record<string, string>} expressions
 * @returns {string}
 */
export function formatExpressions(expressions) {
  return Object.entries(expressions ?? {})
    .map(([name, formula]) => `${name} = ${formula}`)
    .join("\n");
}
