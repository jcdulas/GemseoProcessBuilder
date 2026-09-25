import assert from "node:assert/strict";
import { test } from "node:test";

import { currentMapping, mappingCommands } from "../../gemseo_process_builder/static/js/lib/link_mapping.js";

const links = [
  { id: "l-1", source: { node: "A", port: "u" }, target: { node: "B", port: "x" } },
  { id: "l-2", source: { node: "C", port: "w" }, target: { node: "B", port: "z" } },
];

test("the current mapping: explicit links, then names", () => {
  assert.deepEqual(currentMapping(links, "A", "B", ["x", "y", "z", "t"], ["u", "y"]), {
    x: { output: "u", explicit: true, other: "" },
    y: { output: "y", explicit: false, other: "" },
    z: { output: "", explicit: true, other: "C" },
    t: { output: "", explicit: false, other: "" },
  });
});

test("choices become commands", () => {
  const before = currentMapping(links, "A", "B", ["x", "y", "z", "t"], ["u", "y"]);
  // Nothing changed.
  assert.deepEqual(mappingCommands(links, "A", "B", before, { x: "u", y: "y", z: "", t: "" }), []);
  // x unlinked, t linked to y, z taken from C.
  assert.deepEqual(mappingCommands(links, "A", "B", before, { x: "", y: "y", z: "u", t: "y" }), [
    { type: "deleteLinks", ids: ["l-1", "l-2"] },
    { type: "addLink", source: { node: "A", port: "u" }, target: { node: "B", port: "z" } },
    { type: "addLink", source: { node: "A", port: "y" }, target: { node: "B", port: "t" } },
  ]);
  // Unlinking a coupling by name needs an explicit link elsewhere: y fed by u instead.
  assert.deepEqual(mappingCommands(links, "A", "B", before, { y: "u" }), [
    { type: "addLink", source: { node: "A", port: "u" }, target: { node: "B", port: "y" } },
  ]);
});
