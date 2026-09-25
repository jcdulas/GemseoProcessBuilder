import assert from "node:assert/strict";
import { test } from "node:test";

import {
  enclosingDriver,
  formatVector,
  interfaceCandidates,
  parseVector,
  placement,
  pickerItems,
  roleBadges,
  roleChoices,
  tabsFor,
  withDefaults,
} from "../../gemseo_process_builder/static/js/lib/driver_config.js";

test("each driver kind has its tabs", () => {
  assert.deepEqual(
    tabsFor("doe").map((tab) => tab.id),
    ["design_space", "responses", "algorithm", "formulation", "execution"],
  );
  assert.equal(tabsFor("optimization")[1].label, "Objectives");
  assert.deepEqual(
    tabsFor("mda").map((tab) => tab.id),
    ["mda_settings"],
  );
  assert.deepEqual(tabsFor("unknown"), []);
});

test("nested drivers get an Interface tab before Execution", () => {
  const ids = (/** @type {any[]} */ tabs) => tabs.map((tab) => tab.id);
  assert.deepEqual(ids(tabsFor("doe", "nested")).slice(-2), ["interface", "execution"]);
  assert.deepEqual(ids(tabsFor("optimization", "bilevel")).slice(-2), ["interface", "execution"]);
  assert.ok(!ids(tabsFor("optimization", "model")).includes("interface"));
  assert.deepEqual(ids(tabsFor("mda", "nested")), ["mda_settings"]);
});

test("placement of a driver: model, nested or BiLevel sub-scenario", () => {
  const root = { id: "n-root", type: "assembly" };
  const optimizer = { id: "o", type: "driver", kind: "optimization", config: {} };
  const bilevel = { ...optimizer, config: { formulation: { name: "BiLevel" } } };
  const sub = { id: "s", type: "driver", kind: "optimization" };
  assert.equal(placement(sub, root, "n-root"), "model");
  assert.equal(placement(sub, null, "n-root"), "model");
  assert.equal(placement(sub, optimizer, "n-root"), "nested");
  assert.equal(placement(sub, { id: "g", type: "assembly" }, "n-root"), "nested");
  assert.equal(placement(sub, bilevel, "n-root"), "bilevel");
  assert.equal(placement({ ...sub, kind: "mda" }, optimizer, "n-root"), "model");
});

test("a nested driver gives back its outputs and its design variables", () => {
  const variables = {
    inputs: [
      { name: "a", size: 1 },
      { name: "x", size: 2 },
    ],
    outputs: [{ name: "f", size: 1 }],
  };
  const config = withDefaults({ design_space: [{ variable: "x" }] });
  const candidates = interfaceCandidates(variables, config);
  assert.deepEqual(
    candidates.inputs.map((item) => item.name),
    ["a", "x"],
  );
  assert.deepEqual(
    candidates.outputs.map((item) => item.name),
    ["f", "x"],
  );
});

test("missing configuration fields get their defaults", () => {
  const config = withDefaults({ objectives: [{ variable: "obj" }] });
  assert.deepEqual(config.objectives, [{ variable: "obj" }]);
  assert.deepEqual(config.design_space, []);
  assert.equal(config.execution.n_processes, 1);
});

test("vectors: one value fills the vector and keeps its text", () => {
  assert.deepEqual(parseVector("1e-3", 3), { values: [0.001, 0.001, 0.001], text: "1e-3", error: null });
  assert.deepEqual(parseVector("0, 2.5", 2), { values: [0, 2.5], text: null, error: null });
  assert.deepEqual(parseVector("", 2), { values: [], text: null, error: null });
  assert.equal(parseVector("1, 2", 3).error, "Enter one value or 3 values.");
  assert.equal(parseVector("a", 1).error, "Enter numbers separated by commas.");
  assert.equal(formatVector([0.001, 0.001], "1e-3"), "1e-3");
  assert.equal(formatVector([2, 2], undefined), "2");
  assert.equal(formatVector([1, 2], undefined), "1, 2");
  assert.equal(formatVector([], undefined), "");
});

test("pickers list unused variables first", () => {
  const items = pickerItems(
    [
      { name: "z", size: 2 },
      { name: "a", size: 1 },
      { name: "b", size: 1 },
    ],
    ["a"],
  );
  assert.deepEqual(items, [
    { name: "b", label: "b", enabled: true },
    { name: "z", label: "z (2)", enabled: true },
    { name: "a", label: "a", enabled: false },
  ]);
});

test("roles by driver kind and direction", () => {
  assert.deepEqual(
    roleChoices("optimization", "out").map((choice) => choice.role),
    ["objective", "constraint", "observable"],
  );
  assert.deepEqual(
    roleChoices("doe", "in").map((choice) => choice.role),
    ["design_variable"],
  );
  assert.deepEqual(
    roleChoices("parametric", "in").map((choice) => choice.role),
    ["level"],
  );
  assert.deepEqual(roleChoices("mda", "out"), []);
  assert.equal(roleBadges(["design variable", "objective"]), "DV OBJ");
});

test("the closest driver around a node", () => {
  const nodes = {
    root: { type: "assembly" },
    outer: { id: "outer", type: "driver" },
    group: { type: "assembly" },
    inner: { id: "inner", type: "driver" },
    leaf: { type: "component" },
  };
  const nodeOf = (/** @type {string} */ id) => nodes[/** @type {keyof typeof nodes} */ (id)];
  assert.equal(enclosingDriver(["root", "outer", "group", "leaf"], nodeOf)?.id, "outer");
  assert.equal(enclosingDriver(["root", "outer", "inner", "leaf"], nodeOf)?.id, "inner");
  assert.equal(enclosingDriver(["root", "leaf"], nodeOf), null);
});
