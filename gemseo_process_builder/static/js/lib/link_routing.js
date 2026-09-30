// @ts-check
// Paths of links: forward links are Bézier curves, feedback links go around.
import { linkPath } from "./geometry.js";

const FEEDBACK_MARGIN = 28;
const CORNER = 10;

/**
 * A path from an output back to an input placed before it: it leaves to the
 * right, runs under both nodes, and enters the input from the left.
 *
 * @param {{x: number, y: number}} start - Output anchor.
 * @param {{x: number, y: number}} end - Input anchor.
 * @param {number} bottom - The lowest edge of the two nodes.
 * @returns {string}
 */
export function feedbackPath(start, end, bottom) {
  const below = bottom + FEEDBACK_MARGIN;
  const right = start.x + FEEDBACK_MARGIN;
  const left = end.x - FEEDBACK_MARGIN;
  return [
    `M${start.x},${start.y}`,
    `H${right - CORNER}`,
    `Q${right},${start.y} ${right},${start.y + CORNER}`,
    `V${below - CORNER}`,
    `Q${right},${below} ${right - CORNER},${below}`,
    `H${left + CORNER}`,
    `Q${left},${below} ${left},${below - CORNER}`,
    `V${end.y + CORNER}`,
    `Q${left},${end.y} ${left + CORNER},${end.y}`,
    `H${end.x}`,
  ].join(" ");
}

/**
 * The path of a link, forward or feedback.
 *
 * @param {{x: number, y: number}} start
 * @param {{x: number, y: number}} end
 * @param {{feedback: boolean, bottom: number}} options
 * @returns {string}
 */
export function routeLink(start, end, { feedback, bottom }) {
  return feedback || end.x < start.x ? feedbackPath(start, end, bottom) : linkPath(start, end);
}

/**
 * Where to write the count of an aggregated link: the middle of its ends.
 *
 * @param {{x: number, y: number}} start
 * @param {{x: number, y: number}} end
 * @returns {{x: number, y: number}}
 */
export function labelPosition(start, end) {
  return { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 };
}
