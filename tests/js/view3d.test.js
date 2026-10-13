import assert from "node:assert/strict";
import { test } from "node:test";

import { view3dActions } from "../../gemseo_process_builder/static/js/lib/view3d.js";

const state = { available: true, folders: { 1: "/store/a", 2: "/store/b" }, store: "/store" };

test("one evaluation with a folder opens; two compare", () => {
  const actions = view3dActions(state, 1, [2]);
  assert.deepEqual(actions.open, { enabled: true, reason: "", evaluations: [1] });
  assert.deepEqual(actions.compare, { enabled: true, reason: "", evaluations: [1, 2] });
});

test("compare needs exactly one other evaluation selected", () => {
  assert.match(view3dActions(state, 1, []).compare.reason, /exactly one other/);
  assert.match(view3dActions(state, 1, [1]).compare.reason, /exactly one other/);
  assert.match(view3dActions(state, 1, [2, 3]).compare.reason, /exactly one other/);
  assert.equal(view3dActions(state, 1, [1, 2]).compare.enabled, true);
});

test("an evaluation without a folder, or nastran_view missing, says why", () => {
  const actions = view3dActions(state, 3, [1]);
  assert.equal(actions.open.enabled, false);
  assert.equal(actions.open.reason, "No sizing folder of gemseo_nastran for evaluation 3 in /store.");
  assert.equal(actions.compare.reason, "No sizing folder of gemseo_nastran for evaluation 3 in /store.");
  const missing = view3dActions({ available: false, reason: "nastran_view is not installed.", folders: {} }, 1, []);
  assert.equal(missing.open.reason, "nastran_view is not installed.");
  assert.match(view3dActions(null, 1, []).open.reason, /^Looking for nastran_view/);
});
