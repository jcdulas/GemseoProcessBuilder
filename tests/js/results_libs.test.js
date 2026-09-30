import assert from "node:assert/strict";
import { test } from "node:test";

import { canUseLog, linearDomain, logDomain, tickCount } from "../../gemseo_process_builder/static/js/lib/chart_scales.js";
import { boundsByColumn, normalize } from "../../gemseo_process_builder/static/js/lib/normalize.js";
import { PagedRows } from "../../gemseo_process_builder/static/js/lib/paged_rows.js";

test("linear domains, constant data included", () => {
  assert.deepEqual(linearDomain([3, 1, null, 2, Number.NaN]), [1, 3]);
  assert.deepEqual(linearDomain([5, 5]), [4.5, 5.5]);
  assert.deepEqual(linearDomain([0, 0]), [-1, 1]);
  assert.deepEqual(linearDomain([]), [0, 1]);
});

test("log scales refuse zero and negative values", () => {
  assert.equal(canUseLog([1, 10]), true);
  assert.equal(canUseLog([1, 0]), false);
  assert.equal(canUseLog([-1, 10]), false);
  assert.equal(canUseLog([null]), false);
  assert.equal(logDomain([-1, 10]), null);
  assert.deepEqual(logDomain([2, 20, null]), [2, 20]);
  assert.deepEqual(logDomain([3, 3]), [0.3, 30]);
});

test("tick counts", () => {
  assert.equal(tickCount(50), 2);
  assert.equal(tickCount(400), 5);
  assert.equal(tickCount(5000), 10);
});

test("normalization with bounds", () => {
  assert.equal(normalize(5, 0, 10), 0.5);
  assert.equal(normalize(-10, -10, 10), 0);
  assert.equal(normalize(1, 1, 1), null);
  assert.equal(normalize(1, null, 10), null);
  assert.equal(normalize(1, -Infinity, 10), null);
  assert.equal(normalize(null, 0, 1), null);
  const bounds = boundsByColumn([
    { variable: "x", lower: [0], upper: [10] },
    { variable: "z", size: 2, lower: [-10, 0], upper: [10, 10] },
    { variable: "free", size: 1 },
  ]);
  assert.deepEqual(Object.fromEntries(bounds), {
    x: { lower: 0, upper: 10 },
    "z[0]": { lower: -10, upper: 10 },
    "z[1]": { lower: 0, upper: 10 },
    free: { lower: null, upper: null },
  });
});

test("pages are fetched with one page ahead each way, once", () => {
  const rows = new PagedRows(100);
  assert.deepEqual(rows.missing(0, 40), [0, 1]);
  rows.markLoading(0);
  rows.markLoading(1);
  assert.deepEqual(rows.missing(0, 40), []);
  assert.equal(rows.store("", 0, [[1], [2]], 250), true);
  assert.deepEqual(rows.row(1), [2]);
  assert.equal(rows.row(150), undefined);
  // 250 rows make 3 pages; page 1 is still loading, and there is no page 3.
  assert.deepEqual(rows.missing(210, 249), [2]);
});

test("a new query invalidates the pages and late answers are ignored", () => {
  const rows = new PagedRows(100);
  rows.store("", 0, [[1]], 10);
  assert.equal(rows.setQuery("sort=obj"), true);
  assert.equal(rows.setQuery("sort=obj"), false);
  assert.equal(rows.row(0), undefined);
  assert.equal(rows.total, null);
  assert.equal(rows.store("", 0, [[1]], 10), false);
  assert.equal(rows.store("sort=obj", 0, [[2]], 10), true);
  assert.deepEqual(rows.row(0), [2]);
});

test("constraints at the optimum", async () => {
  const { constraintState } = await import("../../gemseo_process_builder/static/js/lib/constraints.js");
  assert.deepEqual(constraintState(-2, "ineq"), { state: "satisfied", margin: 2 });
  assert.equal(constraintState(-1e-6, "ineq").state, "active");
  assert.equal(constraintState([0.5, -3], "ineq").state, "violated");
  assert.equal(constraintState(0.001, "eq").state, "active");
  assert.equal(constraintState(-0.5, "eq").state, "violated");
});
