import assert from "node:assert/strict";
import { test } from "node:test";

import { appMenuSections, fileName } from "../../gemseo_process_builder/static/js/lib/app_menu.js";
import { BUILTIN_ITEMS } from "../../gemseo_process_builder/static/js/lib/builtins.js";
import { NODE_ICON_PATHS, nodeAppearance } from "../../gemseo_process_builder/static/js/lib/node_icons.js";

const DEFINITIONS = [
  { id: "file.new", menu: "File", label: "New project", shortcuts: ["Ctrl+N"] },
  { id: "file.open", menu: "File", label: "Open project…", shortcuts: ["Ctrl+O"] },
  { id: "file.save", menu: "File", label: "Save", shortcuts: ["Ctrl+S"], separator_before: true },
  { id: "edit.undo", menu: "Edit", label: "Undo", shortcuts: ["Ctrl+Z"], separator_before: true },
  { id: "view.toggleLeft", menu: "View", label: "Show left panel", shortcuts: [] },
];

test("the application menu keeps the menus and the order of the actions", () => {
  const sections = appMenuSections(DEFINITIONS, {
    enabled: (id) => id !== "file.save",
    checked: (id) => (id === "view.toggleLeft" ? true : undefined),
    recent: ["C:\\work\\sellar.gpb.json", "/home/me/beam.gpb.json"],
    displayShortcut: (shortcut) => shortcut.replace("Ctrl", "⌃"),
  });
  assert.deepEqual(
    sections.map((section) => section.title),
    ["File", "Edit", "View"],
  );
  const file = sections[0].items;
  assert.deepEqual(
    file.map((item) => item.id ?? (item.separator ? "|" : item.label)),
    ["file.new", "file.open", "Open recent", "|", "file.save"],
  );
  assert.equal(file[0].shortcut, "⌃+N");
  assert.equal(file[4].enabled, false);
  assert.deepEqual(file[2].items, [
    { label: "sellar.gpb.json", path: "C:\\work\\sellar.gpb.json" },
    { label: "beam.gpb.json", path: "/home/me/beam.gpb.json" },
  ]);
  // No separator opens a menu.
  assert.equal(sections[1].items[0].id, "edit.undo");
  assert.equal(sections[2].items[0].checked, true);
  assert.equal(sections[2].items[0].shortcut, "");
});

test("without recent projects, Open recent is disabled", () => {
  const [file] = appMenuSections(DEFINITIONS, { enabled: () => true, checked: () => undefined, recent: [] });
  const recent = file.items.find((item) => item.label === "Open recent");
  assert.equal(recent?.enabled, false);
  assert.deepEqual(recent?.items, []);
  assert.equal(fileName("a/b/"), "b");
});

test("every built-in node has its own icon and label", () => {
  const seen = new Set();
  for (const item of BUILTIN_ITEMS) {
    const appearance = nodeAppearance(/** @type {any} */ (item.node));
    assert.ok(appearance.icon in NODE_ICON_PATHS, item.id);
    assert.ok(appearance.label, item.id);
    seen.add(appearance.icon);
  }
  assert.equal(seen.size, BUILTIN_ITEMS.length);
  assert.deepEqual(nodeAppearance({ type: "driver", kind: "doe" }), { icon: "doe", label: "DOE", tone: "driver-doe" });
  assert.equal(nodeAppearance({ type: "assembly" }).tone, "assembly");
  assert.equal(nodeAppearance({ type: "component", kind: "surrogate" }).tone, "component");
});

test("unknown kinds still get an icon", () => {
  assert.equal(nodeAppearance({ type: "component", kind: "future" }).icon, "python_class");
  assert.equal(nodeAppearance({ type: "driver", kind: "future" }).tone, "driver-optimization");
});
