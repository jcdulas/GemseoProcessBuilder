import assert from "node:assert/strict";
import { test } from "node:test";

import { matchScore, search, searchEntries } from "../../gemseo_process_builder/static/js/lib/search_index.js";

test("match quality: exact, prefix, word prefix, inside", () => {
  assert.equal(matchScore("y_1", "y_1"), 0);
  assert.equal(matchScore("Sellar1", "sel"), 1);
  assert.equal(matchScore("x_shared", "sha"), 2);
  assert.equal(matchScore("Wing:area", "area"), 2);
  assert.equal(matchScore("Sellar1", "lar"), 3);
  assert.equal(matchScore("Sellar1", "xyz"), null);
});

const NODES = {
  root: { id: "root", name: "Model", type: "assembly" },
  opt: { id: "opt", name: "Optimizer", type: "driver" },
  s1: { id: "s1", name: "Sellar1", type: "component" },
  s2: { id: "s2", name: "Sellar2", type: "component" },
  y: { id: "y", name: "y_1_check", type: "component" },
};
const PATHS = { opt: "Model.Optimizer", s1: "Model.Optimizer.Sellar1", s2: "Model.Optimizer.Sellar2", y: "Model.y_1_check" };
const COUPLINGS = {
  opt: {
    couplings: {
      y_1: { producers: [{ node: "s1", port: "y_1", direction: "out" }], consumers: [{ node: "s2", port: "y_1", direction: "in", kind: "implicit" }] },
      // A nested driver seen through its interface: its components are shown instead.
      obj: { producers: [{ node: "opt", port: "obj", direction: "out" }], consumers: [] },
      "Wing:area": { producers: [{ node: "s2", port: "area", direction: "out" }], consumers: [] },
    },
  },
};

const entries = searchEntries(NODES, (id) => PATHS[id], COUPLINGS, "root");

test("entries: nodes, and variables by global and local name", () => {
  assert.ok(!entries.some((entry) => entry.node === "root"));
  const variables = entries.filter((entry) => entry.kind === "variable").map((entry) => `${entry.name}@${entry.node}`);
  assert.deepEqual(variables, ["y_1@s1", "y_1@s2", "Wing:area@s2", "area@s2"]);
  assert.equal(entries.find((entry) => entry.name === "y_1").detail, "output of Model.Optimizer.Sellar1");
});

test("exact matches first, then nodes before variables", () => {
  const results = search(entries, "y_1");
  assert.deepEqual(
    results.map((result) => [result.kind, result.name, result.node]),
    [
      ["variable", "y_1", "s1"],
      ["variable", "y_1", "s2"],
      ["node", "y_1_check", "y"],
    ],
  );
});

test("prefix and substring matches, and empty queries", () => {
  assert.deepEqual(
    search(entries, "sellar").map((result) => result.name),
    ["Sellar1", "Sellar2"],
  );
  assert.deepEqual(
    search(entries, "area").map((result) => result.name),
    ["area", "Wing:area"],
  );
  assert.deepEqual(search(entries, "  "), []);
  assert.equal(search(entries, "a", 2).length, 2);
});
