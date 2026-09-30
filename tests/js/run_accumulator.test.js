import assert from "node:assert/strict";
import { test } from "node:test";

import { decimate } from "../../gemseo_process_builder/static/js/lib/decimate.js";
import { RunAccumulator, maxViolation } from "../../gemseo_process_builder/static/js/lib/run_accumulator.js";
import { aggregateState, nodeStates } from "../../gemseo_process_builder/static/js/lib/status_aggregation.js";

test("iterations keep the objective and the largest violation", () => {
  const run = new RunAccumulator();
  run.apply("iteration", { index: 1, f: { obj: 22.9 }, g: { c_1: -1, c_2: 0.5 }, h: {}, feasible: false });
  run.apply("iteration", { index: 2, f: { obj: [3.2] }, g: { c_1: [-1, -2] }, h: { e: -0.1 }, feasible: true });
  assert.deepEqual(
    run.iterations.map(({ values, ...point }) => point),
    [
      { index: 1, objective: 22.9, violation: 0.5, feasible: false },
      { index: 2, objective: 3.2, violation: 0.1, feasible: true },
    ],
  );
  assert.deepEqual(run.iterations[1].values, { obj: 3.2, "c_1[0]": -1, "c_1[1]": -2, e: -0.1 });
  assert.equal(run.objectiveName, "obj");
});

test("violations", () => {
  assert.equal(maxViolation({ a: -1 }, {}), 0);
  assert.equal(maxViolation({}, {}), null);
  assert.equal(maxViolation({ a: null }, {}), null);
});

test("samples keep the first two inputs and the first response", () => {
  const run = new RunAccumulator();
  run.apply("sample", { index: 1, inputs: { x: 1, y: [2, 5], z: 3 }, outputs: { f: 10, g: 1 } });
  assert.deepEqual(run.samples, [
    { index: 1, inputs: [1, 2], output: 10, values: { x: 1, "y[0]": 2, "y[1]": 5, z: 3, f: 10, g: 1 } },
  ]);
  assert.deepEqual(run.inputNames, ["x", "y"]);
  assert.equal(run.outputName, "f");
});

test("batches, states and progress", () => {
  const run = new RunAccumulator();
  run.apply("batch", {
    event: "status",
    items: [{ dropped: 3 }, { node_id: "a", state: "running" }, { node_id: "a", state: "done" }],
  });
  run.apply("progress", { current: 2, total: 10, unit: "iteration" });
  assert.equal(run.states.get("a"), "done");
  assert.deepEqual(run.progress, { current: 2, total: 10, unit: "iteration" });
});

test("decimation keeps the first, last, lowest and highest points", () => {
  const points = Array.from({ length: 1000 }, (_, index) => ({ index, value: index === 500 ? -99 : index === 700 ? 999 : 0 }));
  const kept = decimate(points, 20, (point) => point.value);
  assert.ok(kept.length <= 20);
  const indices = kept.map((point) => point.index);
  assert.ok(indices.includes(0) && indices.includes(999) && indices.includes(500) && indices.includes(700));
  assert.deepEqual(indices, [...indices].sort((a, b) => a - b));
  assert.equal(decimate(points.slice(0, 5), 20, (point) => point.value).length, 5);
});

test("memory stays bounded", () => {
  const run = new RunAccumulator({ maxPoints: 100 });
  for (let index = 1; index <= 1000; index += 1) {
    run.apply("iteration", { index, f: { obj: index }, g: {}, h: {} });
  }
  assert.ok(run.iterations.length <= 100);
  assert.equal(run.iterations.at(-1)?.index, 1000);
});

test("container states", () => {
  assert.equal(aggregateState([]), null);
  assert.equal(aggregateState(["done", null, "done"]), "done");
  assert.equal(aggregateState(["pending", "pending"]), "pending");
  assert.equal(aggregateState(["done", "pending"]), "running");
  assert.equal(aggregateState(["done", "running", "pending"]), "running");
  assert.equal(aggregateState(["running", "failed"]), "failed");
  const children = { root: ["driver", "other"], driver: ["a", "group"], group: ["b"], other: [] };
  const states = nodeStates("root", (id) => children[/** @type {keyof children} */ (id)] ?? null, new Map([
    ["a", "done"],
    ["b", "running"],
  ]));
  assert.deepEqual(Object.fromEntries(states), { a: "done", b: "running", group: "running", driver: "running", root: "running" });
});

test("nested scenarios report their own iterations", () => {
  const run = new RunAccumulator();
  run.apply("inner_progress", { node_id: "n-a", name: "A", current: 3 });
  run.apply("inner_progress", { node_id: "n-b", name: "B", current: 1 });
  assert.deepEqual(run.inner.get("n-a"), { name: "A", current: 3 });
  assert.equal(run.lastInner, "n-b");
});
