import assert from "node:assert/strict";
import { test } from "node:test";

import { nodeFromEntry } from "../../gemseo_process_builder/static/js/lib/builtins.js";
import { demoNote, packageSections } from "../../gemseo_process_builder/static/js/lib/library_sections.js";

const entry = (name, group = "", description = "") => ({
  kind: "python_class",
  name,
  module_path: "",
  module: "gemseo_nastran.disciplines",
  attribute: name,
  group,
  description,
});

const PACKAGES = [
  {
    name: "gemseo-nastran",
    version: "0.3.0",
    entries: [entry("StructuralSizing", "Outer loop", "Sizes one architecture."), entry("Mass"), entry("LoadModel", "Loads"), entry("InternalLoads", "Loads")],
    errors: [],
    warnings: ["Entry 9: the key 'color' is unknown and was ignored."],
  },
  { name: "broken-tools", version: "1.0", entries: [], errors: [{ path: "broken_tools.catalog:COMPONENTS", message: "RuntimeError: broken" }] },
];

test("one section per package, titled with its distribution and version", () => {
  const sections = packageSections(PACKAGES, "");
  assert.deepEqual(
    sections.map((section) => [section.key, section.title]),
    [
      ["package:broken-tools", "broken-tools 1.0"],
      ["package:gemseo-nastran", "gemseo-nastran 0.3.0"],
    ],
  );
  assert.equal(sections[0].errors.length, 1);
  assert.deepEqual(sections[0].groups, []);
  assert.deepEqual(sections[1].warnings, PACKAGES[0].warnings);
});

test("the entries are grouped, those without a group first", () => {
  const [, nastran] = packageSections(PACKAGES, "");
  assert.deepEqual(
    nastran.groups.map((group) => [group.title, group.entries.map((item) => item.name)]),
    [
      ["", ["Mass"]],
      ["Outer loop", ["StructuralSizing"]],
      ["Loads", ["LoadModel", "InternalLoads"]],
    ],
  );
  assert.deepEqual(nastran.groups[0].entries[0].package, { name: "gemseo-nastran", version: "0.3.0" });
});

test("a search keeps the matching entries and hides errors and warnings", () => {
  const sections = packageSections(PACKAGES, "architecture");
  assert.equal(sections.length, 1);
  assert.deepEqual(sections[0].groups.map((group) => group.entries.map((item) => item.name)), [["StructuralSizing"]]);
  assert.deepEqual([sections[0].errors, sections[0].warnings], [[], []]);
  assert.deepEqual(packageSections(PACKAGES, "nothing like this"), []);
});

test("an entry of a package becomes a component importing its module", () => {
  const [, nastran] = packageSections(PACKAGES, "");
  const sizing = nastran.groups[1].entries[0];
  assert.deepEqual(nodeFromEntry(sizing), {
    type: "component",
    kind: "python_class",
    name: "StructuralSizing",
    config: {
      module: "gemseo_nastran.disciplines",
      class: "StructuralSizing",
      package: { name: "gemseo-nastran", version: "0.3.0" },
      init_args: {},
    },
  });
  const drag = { ...sizing, kind: "python_function", name: "drag", attribute: "drag" };
  assert.deepEqual(nodeFromEntry(drag).config, {
    module: "gemseo_nastran.disciplines",
    function: "drag",
    package: { name: "gemseo-nastran", version: "0.3.0" },
  });
});

test("a demo notes the packages missing from the Python of the runs", () => {
  assert.equal(demoNote([]), "");
  assert.equal(demoNote(["gemseo_nastran", "nastran_loads"]), "Needs gemseo_nastran, nastran_loads, missing from the Python of the runs.");
});
