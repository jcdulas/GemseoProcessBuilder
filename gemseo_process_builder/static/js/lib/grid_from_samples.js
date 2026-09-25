// @ts-check
// A 2-D grid of values from the samples of a full-factorial study.

/**
 * The distinct values of a list, sorted.
 *
 * @param {(number | null)[]} values
 * @returns {number[]}
 */
export function levels(values) {
  const numbers = /** @type {number[]} */ (values.filter((value) => typeof value === "number" && Number.isFinite(value)));
  return [...new Set(numbers)].sort((a, b) => a - b);
}

/**
 * Arrange samples on the grid of their x and y levels.
 *
 * @param {(number | null)[]} xs
 * @param {(number | null)[]} ys
 * @param {(number | null)[]} zs
 * @returns {{x: number[], y: number[], values: (number | null)[][]}} ``values[j][i]``
 *   holds the sample at ``x[i]``, ``y[j]``; ``null`` where no sample was evaluated.
 */
export function gridFromSamples(xs, ys, zs) {
  const x = levels(xs);
  const y = levels(ys);
  const column = new Map(x.map((value, index) => [value, index]));
  const row = new Map(y.map((value, index) => [value, index]));
  /** @type {(number | null)[][]} */
  const values = y.map(() => x.map(() => null));
  zs.forEach((z, index) => {
    const i = column.get(/** @type {number} */ (xs[index]));
    const j = row.get(/** @type {number} */ (ys[index]));
    if (i !== undefined && j !== undefined && typeof z === "number" && Number.isFinite(z)) {
      values[j][i] = z;
    }
  });
  return { x, y, values };
}

/**
 * A finer grid by bilinear interpolation, for smooth contour lines.
 *
 * The coarse values sit at the corners of the fine grid: a coarse grid of
 * ``nx`` by ``ny`` values gives ``(nx - 1) * factor + 1`` by
 * ``(ny - 1) * factor + 1`` values, in the same row-major order.
 *
 * @param {number[][]} values - ``values[j][i]``, complete.
 * @param {number} factor
 * @returns {{width: number, height: number, values: number[]}}
 */
export function resample(values, factor) {
  const ny = values.length;
  const nx = values[0].length;
  const width = (nx - 1) * factor + 1;
  const height = (ny - 1) * factor + 1;
  const fine = [];
  for (let row = 0; row < height; row += 1) {
    const y = row / factor;
    const j = Math.min(Math.floor(y), ny - 2);
    const ty = y - j;
    for (let column = 0; column < width; column += 1) {
      const x = column / factor;
      const i = Math.min(Math.floor(x), nx - 2);
      const tx = x - i;
      const bottom = values[j][i] * (1 - tx) + values[j][i + 1] * tx;
      const top = values[j + 1][i] * (1 - tx) + values[j + 1][i + 1] * tx;
      fine.push(bottom * (1 - ty) + top * ty);
    }
  }
  return { width, height, values: fine };
}
