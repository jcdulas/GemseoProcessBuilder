import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CACHE_CHOICES,
  cacheApplies,
  cacheChoice,
  cacheFields,
  cacheOf,
  cacheValues,
  defaultNodePath,
  entriesText,
  settingFor,
} from "../../gemseo_process_builder/static/js/lib/cache_setting.js";

const component = { type: "component", config: { expressions: { y: "x" }, cache: { type: "memory" } } };
const group = { type: "assembly", cache: { type: "hdf5", file: "/data/study.h5", node: "Study/Group" } };

test("the default is GEMSEO's last execution, absent from the node", () => {
  assert.equal(CACHE_CHOICES[0].value, "default");
  assert.equal(cacheChoice(cacheOf({ type: "component", config: {} })), "default");
  assert.equal(cacheChoice(cacheOf({ type: "assembly", cache: {} })), "default");
  assert.equal(cacheChoice(cacheOf(component)), "memory");
  assert.equal(cacheChoice(cacheOf(group)), "hdf5");
});

test("the fields shown per choice", () => {
  assert.deepEqual(cacheFields("default"), { tolerance: false, file: false, node: false, entries: false });
  assert.deepEqual(cacheFields("none"), { tolerance: false, file: false, node: false, entries: false });
  assert.deepEqual(cacheFields("memory"), { tolerance: true, file: false, node: false, entries: false });
  assert.deepEqual(cacheFields("hdf5"), { tolerance: true, file: true, node: true, entries: true });
});

test("a choice keeps what still applies, and fills the defaults of a file", () => {
  const defaults = { file: "/data/caches/Study.h5", node: defaultNodePath(["Model", "Study", "Sizing"]) };
  assert.equal(defaults.node, "Study/Sizing");
  assert.equal(settingFor("default", cacheOf(component), defaults), null);
  assert.deepEqual(settingFor("hdf5", { type: "memory", tolerance: 1e-6 }, defaults), {
    type: "hdf5",
    tolerance: 1e-6,
    file: "/data/caches/Study.h5",
    node: "Study/Sizing",
  });
  assert.deepEqual(settingFor("memory", cacheOf(group), defaults), { type: "memory" });
  assert.deepEqual(settingFor("none", { type: "memory", tolerance: 1e-6 }, defaults), { type: "none" });
});

test("the values of the command: the config of a component, the field of an assembly", () => {
  assert.deepEqual(cacheValues(component, null), { config: { expressions: { y: "x" } } });
  assert.deepEqual(cacheValues(component, { type: "none" }), { config: { expressions: { y: "x" }, cache: { type: "none" } } });
  assert.deepEqual(cacheValues(group, null), { cache: {} });
});

test("where a cache applies: the nodes the script builds as disciplines", () => {
  assert.equal(cacheApplies({ type: "assembly" }, 0), false); // The model.
  assert.equal(cacheApplies({ type: "component" }, 1), true);
  assert.equal(cacheApplies({ type: "assembly", transparent: true }, 2), false);
  assert.equal(cacheApplies({ type: "driver" }, 1), false); // A study of its own.
  assert.equal(cacheApplies({ type: "driver" }, 2), true);
});

test("the entries of a file cache", () => {
  assert.match(entriesText({ exists: false, entries: 0, differs: false }), /first run/);
  assert.equal(entriesText({ exists: true, entries: 1, differs: false }), "1 entry kept in the file.");
  assert.match(entriesText({ exists: true, entries: 4, differs: true }), /^4 entries, computed by another version/);
});
