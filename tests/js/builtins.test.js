import assert from "node:assert/strict";
import { test } from "node:test";

import { BUILTIN_ITEMS, nodeFromEntry, searchItems, toNodeName } from "../../gemseo_process_builder/static/js/lib/builtins.js";

test("built-in items have unique ids and valid names", () => {
  assert.equal(new Set(BUILTIN_ITEMS.map((item) => item.id)).size, BUILTIN_ITEMS.length);
  for (const item of BUILTIN_ITEMS) {
    assert.match(item.node.name, /^[A-Za-z][A-Za-z0-9_]*$/);
  }
});

test("catalog entries become nodes", () => {
  assert.deepEqual(nodeFromEntry({ kind: "python_class", name: "Wing", module_path: "/m.py", attribute: "Wing" }), {
    type: "component",
    kind: "python_class",
    name: "Wing",
    config: { module_path: "/m.py", class: "Wing", init_args: {} },
  });
  assert.equal(nodeFromEntry({ kind: "python_function", name: "lift", module_path: "/m.py", attribute: "lift" }).config.function, "lift");
  assert.equal(nodeFromEntry({ kind: "executable", name: "my-solver", module_path: "/s.gpbwrap.json", attribute: "" }).name, "my_solver");
});

test("node names are cleaned", () => {
  assert.equal(toNodeName("2nd stage"), "nd_stage");
  assert.equal(toNodeName("###"), "Component");
});

test("search in labels and descriptions", () => {
  assert.deepEqual(searchItems(BUILTIN_ITEMS, "sweeps").map((item) => item.id), ["builtin.parametric"]);
  assert.ok(searchItems(BUILTIN_ITEMS, "external program").some((item) => item.id === "builtin.executable"));
  assert.equal(searchItems(BUILTIN_ITEMS, "").length, BUILTIN_ITEMS.length);
});
