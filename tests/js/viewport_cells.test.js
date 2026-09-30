import assert from "node:assert/strict";
import { test } from "node:test";

import { cellsInView, visibleCells, visibleRange } from "../../gemseo_process_builder/static/js/lib/viewport_cells.js";

test("the whole grid when it fits", () => {
  assert.deepEqual(visibleRange(0, 1, 500, 20, 10), [0, 9]);
});

test("cells cut by the edges are visible", () => {
  // Shifted by half a cell: cell 0 is half visible, cell 5 too.
  assert.deepEqual(visibleRange(-10, 1, 100, 20, 50), [0, 5]);
  // 25 cells scrolled away, 3.5 cells visible.
  assert.deepEqual(visibleRange(-500, 1, 70, 20, 50), [25, 28]);
});

test("zoom changes the visible count", () => {
  assert.deepEqual(visibleRange(0, 2, 100, 20, 50), [0, 2]);
  assert.deepEqual(visibleRange(0, 0.1, 100, 20, 50), [0, 49]);
});

test("nothing visible beyond the grid", () => {
  const [first, last] = visibleRange(-2000, 1, 100, 20, 50);
  assert.ok(first > last);
  const [before, after] = visibleRange(300, 1, 100, 20, 50);
  assert.ok(before > after);
  assert.deepEqual(visibleRange(0, 1, 100, 20, 0), [0, -1]);
});

test("rows follow y and columns follow x", () => {
  assert.deepEqual(visibleCells({ x: -200, y: 0, k: 1 }, 100, 60, 20, 50), { rows: [0, 2], cols: [10, 14] });
});

test("only the cells of visible rows and columns", () => {
  const byRow = new Map([
    [0, [{ col: 1 }, { col: 5 }, { col: 9 }]],
    [3, [{ col: 4 }]],
    [8, [{ col: 2 }]],
  ]);
  assert.deepEqual(cellsInView(byRow, { rows: [0, 5], cols: [2, 6] }), [{ col: 5 }, { col: 4 }]);
});
