// @ts-check
// Which rows and columns of a square grid are visible (N2 virtualization).

/**
 * The indices of the grid lines visible along one axis.
 *
 * A point ``p`` of the grid is drawn at ``offset + scale * p``.
 *
 * @param {number} offset - Translation of the grid, in pixels.
 * @param {number} scale - Zoom factor.
 * @param {number} length - Visible length, in pixels.
 * @param {number} size - Size of a cell, in grid units.
 * @param {number} count - Number of cells along the axis.
 * @returns {[number, number]} First and last visible indices, cells cut by the
 *   edges included; ``first > last`` when nothing is visible.
 */
export function visibleRange(offset, scale, length, size, count) {
  if (count <= 0 || scale <= 0 || size <= 0) {
    return [0, -1];
  }
  const low = -offset / scale / size;
  const high = (length - offset) / scale / size;
  const first = Math.max(0, Math.floor(low));
  const last = Math.min(count - 1, Math.ceil(high) - 1);
  return [first, last];
}

/**
 * The visible rows and columns of a square grid.
 *
 * @param {{x: number, y: number, k: number}} transform
 * @param {number} width - Viewport width, in pixels.
 * @param {number} height - Viewport height, in pixels.
 * @param {number} size - Size of a cell, in grid units.
 * @param {number} count - Number of rows (and columns).
 * @returns {{rows: [number, number], cols: [number, number]}}
 */
export function visibleCells(transform, width, height, size, count) {
  return {
    rows: visibleRange(transform.y, transform.k, height, size, count),
    cols: visibleRange(transform.x, transform.k, width, size, count),
  };
}

/**
 * The cells of the visible rows whose column is visible too.
 *
 * @template {{col: number}} T
 * @param {Map<number, T[]>} byRow - Cells of each row, sorted by column.
 * @param {{rows: [number, number], cols: [number, number]}} visible
 * @returns {T[]}
 */
export function cellsInView(byRow, visible) {
  const [firstCol, lastCol] = visible.cols;
  /** @type {T[]} */
  const found = [];
  for (let row = visible.rows[0]; row <= visible.rows[1]; row += 1) {
    for (const cell of byRow.get(row) ?? []) {
      if (cell.col > lastCol) {
        break;
      }
      if (cell.col >= firstCol) {
        found.push(cell);
      }
    }
  }
  return found;
}
