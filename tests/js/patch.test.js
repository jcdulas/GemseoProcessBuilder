import assert from "node:assert/strict";
import { test } from "node:test";

import {
  applyChanges,
  checkRevision,
  childrenOf,
  fromSnapshot,
  linksOf,
  pathTo,
} from "../../gemseo_process_builder/static/js/lib/patch.js";

function sampleState() {
  return fromSnapshot({
    rev: 3,
    root: "n-root",
    nodes: {
      "n-root": { id: "n-root", name: "Model", parent: null, children: ["n-g", "n-a"] },
      "n-g": { id: "n-g", name: "G", parent: "n-root", children: ["n-b"] },
      "n-a": { id: "n-a", name: "A", parent: "n-root" },
      "n-b": { id: "n-b", name: "B", parent: "n-g" },
    },
    links: { "l-1": { id: "l-1", source: { node: "n-a", port: "y" }, target: { node: "n-b", port: "y" } } },
    layout: { "n-a": { x: 1, y: 2 } },
    levels: {},
    view: {},
    project: {},
  });
}

test("changes upsert and delete entities", () => {
  const state = sampleState();
  const touched = applyChanges(state, [
    { op: "upsert", kind: "node", id: "n-a", data: { id: "n-a", name: "Aero", parent: "n-root" } },
    { op: "delete", kind: "link", id: "l-1" },
    { op: "upsert", kind: "layout", id: "n-b", data: { x: 5, y: 6 } },
  ]);
  assert.equal(state.nodes["n-a"].name, "Aero");
  assert.equal(state.links["l-1"], undefined);
  assert.deepEqual(state.layout["n-b"], { x: 5, y: 6 });
  assert.deepEqual([...touched], ["node:n-a", "link:l-1", "layout:n-b"]);
});

test("unknown kinds are an error", () => {
  assert.throws(() => applyChanges(sampleState(), [{ op: "upsert", kind: "alien", id: "x" }]));
});

test("children keep their order", () => {
  assert.deepEqual(
    childrenOf(sampleState(), "n-root").map((node) => node.name),
    ["G", "A"],
  );
  assert.deepEqual(childrenOf(sampleState(), "n-a"), []);
});

test("paths go from the root to the node", () => {
  assert.deepEqual(pathTo(sampleState(), "n-b"), ["n-root", "n-g", "n-b"]);
});

test("links of a set of nodes", () => {
  assert.equal(linksOf(sampleState(), new Set(["n-b"])).length, 1);
  assert.equal(linksOf(sampleState(), new Set(["n-g"])).length, 0);
});

test("revision checks detect stale patches and gaps", () => {
  assert.equal(checkRevision(3, 4), "apply");
  assert.equal(checkRevision(3, 3), "stale");
  assert.equal(checkRevision(3, 6), "gap");
});

test("snapshots are copied, not shared", () => {
  const snapshot = { rev: 1, root: "r", nodes: {}, links: {}, layout: {}, levels: {}, view: {}, project: {} };
  const state = fromSnapshot(snapshot);
  state.nodes.x = {};
  assert.deepEqual(snapshot.nodes, {});
});
