import assert from "node:assert/strict";
import { test } from "node:test";

import { gridFromSamples, levels } from "../../gemseo_process_builder/static/js/lib/grid_from_samples.js";

test("a full-factorial grid, with a missing point", () => {
  const xs = [0, 1, 2, 0, 1, 2, 0, 1];
  const ys = [5, 5, 5, 6, 6, 6, 7, 7];
  const zs = [1, 2, 3, 4, 5, 6, 7, 8];
  assert.deepEqual(gridFromSamples(xs, ys, zs), {
    x: [0, 1, 2],
    y: [5, 6, 7],
    values: [
      [1, 2, 3],
      [4, 5, 6],
      [7, 8, null],
    ],
  });
});

test("levels ignore missing values and duplicates", () => {
  assert.deepEqual(levels([2, null, 1, 2, Number.NaN]), [1, 2]);
});

test("bilinear resampling keeps the corners and interpolates between them", async () => {
  const { resample } = await import("../../gemseo_process_builder/static/js/lib/grid_from_samples.js");
  const fine = resample(
    [
      [0, 10],
      [20, 30],
    ],
    2,
  );
  assert.deepEqual(fine, { width: 3, height: 3, values: [0, 5, 10, 10, 15, 20, 20, 25, 30] });
});
