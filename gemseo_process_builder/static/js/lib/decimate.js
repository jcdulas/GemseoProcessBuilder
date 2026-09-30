// @ts-check
// Fewer points to draw, keeping the shape of the data.

/**
 * Keep at most ``count`` points: in each bucket, the first, last, lowest and
 * highest values survive, so the shape of the curve is preserved.
 *
 * @template T
 * @param {T[]} points
 * @param {number} count
 * @param {(point: T) => number | null} valueOf
 * @returns {T[]}
 */
export function decimate(points, count, valueOf) {
  if (points.length <= count) {
    return points;
  }
  const buckets = Math.max(1, Math.floor(count / 4));
  const size = points.length / buckets;
  /** @type {Set<number>} */
  const kept = new Set();
  for (let bucket = 0; bucket < buckets; bucket += 1) {
    const start = Math.floor(bucket * size);
    const end = Math.min(points.length, Math.floor((bucket + 1) * size));
    kept.add(start).add(end - 1);
    let lowest = { index: -1, value: Number.POSITIVE_INFINITY };
    let highest = { index: -1, value: Number.NEGATIVE_INFINITY };
    for (let index = start; index < end; index += 1) {
      const value = valueOf(points[index]);
      if (value !== null && value < lowest.value) {
        lowest = { index, value };
      }
      if (value !== null && value > highest.value) {
        highest = { index, value };
      }
    }
    for (const extreme of [lowest, highest]) {
      if (extreme.index >= 0) {
        kept.add(extreme.index);
      }
    }
  }
  return [...kept].sort((a, b) => a - b).map((index) => points[index]);
}

/**
 * Evenly spaced positions, at most ``count`` of them among ``length``, first
 * and last included (for clouds of points, where extremes are not the point).
 *
 * @param {number} length
 * @param {number} count
 * @returns {number[]}
 */
export function evenPositions(length, count) {
  if (length <= count) {
    return Array.from({ length }, (_, index) => index);
  }
  const step = (length - 1) / (count - 1);
  return Array.from({ length: count }, (_, index) => Math.round(index * step));
}
