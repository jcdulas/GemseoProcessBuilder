// @ts-check
// Design variables scaled to [0, 1] with their bounds, to compare them on one chart.

/**
 * A value scaled between its bounds: 0 at the lower bound, 1 at the upper one.
 *
 * Without finite and distinct bounds, the value cannot be scaled: ``null``.
 *
 * @param {number | null} value
 * @param {number | null | undefined} lower
 * @param {number | null | undefined} upper
 * @returns {number | null}
 */
export function normalize(value, lower, upper) {
  if (value === null || !Number.isFinite(value)) {
    return null;
  }
  if (typeof lower !== "number" || typeof upper !== "number" || !Number.isFinite(lower) || !Number.isFinite(upper)) {
    return null;
  }
  if (upper === lower) {
    return null;
  }
  return (value - lower) / (upper - lower);
}

/**
 * The bounds of each column of the design variables, from the driver's design
 * space (a single bound applies to every element of a vector).
 *
 * @param {any[]} designSpace - ``config.design_space`` of the driver.
 * @returns {Map<string, {lower: number | null, upper: number | null}>} By column name.
 */
export function boundsByColumn(designSpace) {
  /** @type {Map<string, {lower: number | null, upper: number | null}>} */
  const bounds = new Map();
  for (const variable of designSpace ?? []) {
    const size = variable.size ?? 1;
    for (let index = 0; index < size; index += 1) {
      const name = size > 1 ? `${variable.variable}[${index}]` : variable.variable;
      bounds.set(name, {
        lower: variable.lower?.length ? (variable.lower[index] ?? null) : null,
        upper: variable.upper?.length ? (variable.upper[index] ?? null) : null,
      });
    }
  }
  return bounds;
}
