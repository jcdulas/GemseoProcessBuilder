// @ts-check
// Whether constraints hold at a point, with GEMSEO's default tolerances.

const INEQUALITY_TOLERANCE = 1e-4;
const EQUALITY_TOLERANCE = 1e-2;

/**
 * The state of a constraint at the optimum, and its margin.
 *
 * @param {number | number[]} value
 * @param {"eq" | "ineq" | null} type
 * @returns {{state: "active" | "violated" | "satisfied", margin: number}}
 */
export function constraintState(value, type) {
  const values = Array.isArray(value) ? value : [value];
  if (type === "eq") {
    const gap = Math.max(...values.map(Math.abs));
    return { state: gap <= EQUALITY_TOLERANCE ? "active" : "violated", margin: -gap };
  }
  const worst = Math.max(...values);
  if (worst > INEQUALITY_TOLERANCE) {
    return { state: "violated", margin: -worst };
  }
  return { state: worst >= -INEQUALITY_TOLERANCE ? "active" : "satisfied", margin: -worst };
}
