import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { binCounts, binIndex, binRange, maxCount } from "../../gemseo_process_builder/static/js/lib/binning.js";

test("the JS bins match the worker's on the shared case", () => {
  const shared = JSON.parse(readFileSync(new URL("fixtures/binning_case.json", import.meta.url), "utf-8"));
  assert.deepEqual(binCounts(shared.x, shared.y, shared.bins), shared.expected);
});

test("single point and identical values", () => {
  assert.deepEqual(binRange([2]), [1.5, 2.5]);
  assert.deepEqual(binRange([]), [0, 1]);
  assert.deepEqual(binCounts([2, 2], [5, 5], 2).counts, [
    [0, 0],
    [0, 2],
  ]);
  assert.equal(binIndex(null, [0, 1], 4), -1);
  assert.equal(binIndex(1, [0, 1], 4), 3);
  assert.equal(maxCount([[0, 0]]), 1);
  assert.equal(maxCount([[0, 7], [3, 1]]), 7);
});
