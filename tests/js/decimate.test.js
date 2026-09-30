import assert from "node:assert/strict";
import { test } from "node:test";

import { decimate, evenPositions } from "../../gemseo_process_builder/static/js/lib/decimate.js";

test("decimation keeps the extremes of each bucket", () => {
  const points = Array.from({ length: 1000 }, (_, index) => ({ index, value: Math.sin(index / 10) }));
  points[333].value = 50;
  points[666].value = -50;
  const kept = decimate(points, 40, (point) => point.value).map((point) => point.index);
  assert.ok(kept.length <= 40);
  for (const index of [0, 333, 666, 999]) {
    assert.ok(kept.includes(index), `point ${index} kept`);
  }
});

test("even positions", () => {
  assert.deepEqual(evenPositions(3, 10), [0, 1, 2]);
  assert.deepEqual(evenPositions(11, 3), [0, 5, 10]);
});
