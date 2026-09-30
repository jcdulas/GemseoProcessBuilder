// @ts-check
// Rectangular bins of points, for scatter plots with many points.
// ``results/reader.py`` computes the same bins in the worker for large runs.
import { extent } from "./chart_scales.js";

/**
 * The range covered by the bins; a constant gets a width of 1.
 *
 * @param {(number | null)[]} values
 * @returns {[number, number]}
 */
export function binRange(values) {
  const numbers = /** @type {number[]} */ (values.filter((value) => typeof value === "number" && Number.isFinite(value)));
  if (!numbers.length) {
    return [0, 1];
  }
  const [low, high] = extent(numbers);
  return low === high ? [low - 0.5, high + 0.5] : [low, high];
}

/**
 * The bin of a value; the highest value goes in the last bin, a missing one in -1.
 *
 * @param {number | null} value
 * @param {[number, number]} range
 * @param {number} bins
 */
export function binIndex(value, [low, high], bins) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return -1;
  }
  return Math.min(bins - 1, Math.max(0, Math.floor(((value - low) / (high - low)) * bins)));
}

/**
 * Counts of points: ``counts[i][j]`` for x bin ``i`` and y bin ``j``.
 *
 * @param {(number | null)[]} xs
 * @param {(number | null)[]} ys
 * @param {number} bins
 * @returns {{x: [number, number], y: [number, number], counts: number[][]}}
 */
export function binCounts(xs, ys, bins) {
  const x = binRange(xs);
  const y = binRange(ys);
  const counts = Array.from({ length: bins }, () => Array(bins).fill(0));
  xs.forEach((value, index) => {
    const i = binIndex(value, x, bins);
    const j = binIndex(ys[index], y, bins);
    if (i >= 0 && j >= 0) {
      counts[i][j] += 1;
    }
  });
  return { x, y, counts };
}

/**
 * The largest count, for the color scale (at least 1).
 *
 * @param {number[][]} counts
 */
export function maxCount(counts) {
  let highest = 1;
  for (const row of counts) {
    for (const count of row) {
      highest = Math.max(highest, count);
    }
  }
  return highest;
}
