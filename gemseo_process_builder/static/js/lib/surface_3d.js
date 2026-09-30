// @ts-check
// A surface z(x, y) seen in perspective-free 3D, drawn as SVG polygons: the
// grid is scaled into a unit box, turned around the vertical axis (azimuth),
// tilted toward the viewer (elevation), and its cells are sorted from the
// farthest to the nearest (painter's algorithm). Pure: no DOM.

/**
 * @typedef {object} View
 * @property {number} azimuth - Turn around the vertical axis, in radians.
 * @property {number} elevation - Height of the eye above the horizontal plane, in radians.
 */

/**
 * @typedef {object} Projected
 * @property {number} x - To the right of the screen, in box units.
 * @property {number} y - Down the screen, in box units.
 * @property {number} depth - Larger is farther from the viewer.
 */

/** The height of the box relative to its sides. */
export const HEIGHT = 0.6;

/**
 * Project a point of the unit box, each coordinate between 0 and 1.
 *
 * @param {View} view
 * @param {number} u - Along x.
 * @param {number} v - Along y.
 * @param {number} w - Along z.
 * @returns {Projected}
 */
export function project(view, u, v, w) {
  const x = u - 0.5;
  const y = v - 0.5;
  const z = (w - 0.5) * HEIGHT;
  const cos = Math.cos(view.azimuth);
  const sin = Math.sin(view.azimuth);
  const across = x * cos - y * sin;
  const along = x * sin + y * cos;
  const up = Math.sin(view.elevation);
  const flat = Math.cos(view.elevation);
  return { x: across, y: -(along * up + z * flat), depth: along * flat - z * up };
}

/**
 * The finite range of a grid, widened when it is constant.
 *
 * @param {(number | null)[][]} grid
 * @returns {[number, number]}
 */
export function gridRange(grid) {
  let low = Infinity;
  let high = -Infinity;
  for (const row of grid) {
    for (const value of row) {
      if (value !== null && Number.isFinite(value)) {
        low = Math.min(low, value);
        high = Math.max(high, value);
      }
    }
  }
  if (low > high) {
    return [0, 1];
  }
  return low === high ? [low - 0.5, high + 0.5] : [low, high];
}

/**
 * The cells of a surface as polygons, from the farthest to the nearest.
 *
 * @param {(number | null)[][]} grid - `grid[j][i]`: the value at the i-th x and the j-th y.
 * @param {View} view
 * @param {[number, number]} [range] - The values at the bottom and the top of the box.
 * @returns {{points: [number, number][], value: number, depth: number}[]}
 */
export function surfaceCells(grid, view, range = gridRange(grid)) {
  const rows = grid.length;
  const columns = rows ? grid[0].length : 0;
  if (rows < 2 || columns < 2) {
    return [];
  }
  const [low, high] = range;
  const height = (/** @type {number} */ value) => (value - low) / (high - low);
  /** @type {(Projected | null)[][]} */
  const projected = grid.map((row, j) =>
    row.map((value, i) =>
      value === null || !Number.isFinite(value) ? null : project(view, i / (columns - 1), j / (rows - 1), height(value)),
    ),
  );
  const cells = [];
  for (let j = 0; j < rows - 1; j += 1) {
    for (let i = 0; i < columns - 1; i += 1) {
      const corners = [projected[j][i], projected[j][i + 1], projected[j + 1][i + 1], projected[j + 1][i]];
      if (corners.some((corner) => corner === null)) {
        continue;
      }
      const points = /** @type {Projected[]} */ (corners);
      const values = [grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]];
      cells.push({
        points: points.map((point) => /** @type {[number, number]} */ ([point.x, point.y])),
        value: /** @type {number[]} */ (values).reduce((sum, value) => sum + value, 0) / 4,
        depth: points.reduce((sum, point) => sum + point.depth, 0) / 4,
      });
    }
  }
  return cells.sort((a, b) => b.depth - a.depth);
}

/**
 * The value of a grid between its nodes (bilinear interpolation).
 *
 * @param {(number | null)[][]} grid
 * @param {number} fi - Fractional index along x.
 * @param {number} fj - Fractional index along y.
 */
export function interpolate(grid, fi, fj) {
  const rows = grid.length;
  const columns = grid[0]?.length ?? 0;
  const i = Math.max(0, Math.min(columns - 2, Math.floor(fi)));
  const j = Math.max(0, Math.min(rows - 2, Math.floor(fj)));
  const s = Math.max(0, Math.min(1, fi - i));
  const t = Math.max(0, Math.min(1, fj - j));
  const values = [grid[j][i], grid[j][i + 1], grid[j + 1][i], grid[j + 1][i + 1]];
  if (values.some((value) => value === null)) {
    return null;
  }
  const [a, b, c, d] = /** @type {number[]} */ (values);
  return (1 - t) * ((1 - s) * a + s * b) + t * ((1 - s) * c + s * d);
}

/**
 * The fractional grid index of a point of a d3 contour: d3 puts the value of
 * index `i` in the middle of the pixel `[i, i + 1]`.
 *
 * @param {number} coordinate
 * @param {number} size - The number of grid values along this axis.
 */
export function contourIndex(coordinate, size) {
  return Math.max(0, Math.min(size - 1, coordinate - 0.5));
}

/**
 * A value of an axis at a fractional index of its evenly spaced values.
 *
 * @param {number[]} values
 * @param {number} index
 */
export function valueAt(values, index) {
  if (values.length < 2) {
    return values[0] ?? 0;
  }
  const step = (values[values.length - 1] - values[0]) / (values.length - 1);
  return values[0] + index * step;
}

/**
 * The segments of the line where a grid equals a level (marching squares),
 * in fractional grid indices `[i, j]`. Unlike the filled contours of d3, it
 * does not follow the edges of the grid.
 *
 * @param {(number | null)[][]} grid
 * @param {number} level
 * @returns {[[number, number], [number, number]][]}
 */
export function isoSegments(grid, level) {
  /** @type {[[number, number], [number, number]][]} */
  const segments = [];
  for (let j = 0; j < grid.length - 1; j += 1) {
    for (let i = 0; i < grid[j].length - 1; i += 1) {
      const corners = [grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]];
      if (corners.some((value) => value === null || !Number.isFinite(value))) {
        continue;
      }
      const [a, b, c, d] = /** @type {number[]} */ (corners).map((value) => value - level);
      /** The crossing of an edge between two corners, or null. */
      const cross = (
        /** @type {number} */ from,
        /** @type {number} */ to,
        /** @type {[number, number]} */ start,
        /** @type {[number, number]} */ end,
      ) => {
        if (from < 0 === to < 0) {
          return null;
        }
        const t = from / (from - to);
        return /** @type {[number, number]} */ ([start[0] + t * (end[0] - start[0]), start[1] + t * (end[1] - start[1])]);
      };
      const bottom = cross(a, b, [i, j], [i + 1, j]);
      const right = cross(b, c, [i + 1, j], [i + 1, j + 1]);
      const top = cross(d, c, [i, j + 1], [i + 1, j + 1]);
      const left = cross(a, d, [i, j], [i, j + 1]);
      const found = [bottom, right, top, left].filter((point) => point !== null);
      if (found.length === 2) {
        segments.push(/** @type {[[number, number], [number, number]]} */ (found));
      } else if (found.length === 4) {
        // A saddle: the value at the center decides how the crossings pair.
        const centerAbove = (a + b + c + d) / 4 >= 0;
        const aAbove = a >= 0;
        const pairs = centerAbove === aAbove ? [[bottom, right], [top, left]] : [[bottom, left], [top, right]];
        segments.push(.../** @type {[[number, number], [number, number]][]} */ (pairs));
      }
    }
  }
  return segments;
}

/**
 * The grid values flattened for d3.contours (x fastest), with the values
 * outside the region as `NaN`.
 *
 * @param {(number | null)[][]} grid
 */
export function flatten(grid) {
  return grid.flatMap((row) => row.map((value) => (value === null ? Number.NaN : value)));
}
