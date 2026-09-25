import assert from "node:assert/strict";
import { test } from "node:test";

import { cellsByRow, collapse, reorder, siblings } from "../../gemseo_process_builder/static/js/lib/n2_layout.js";

/** A in Group, B in Inner (in Group), C at the level: A -> B -> C, C -> A. */
function data() {
  const entry = (id, parent, depth) => ({ id, name: id, type: "component", kind: "analytic", parent, depth });
  return {
    level: "root",
    entries: [entry("A", "Group", 1), entry("B", "Inner", 2), entry("C", "root", 0)],
    blocks: [
      { id: "Group", name: "Group", mode: "auto", parent: "root", depth: 0, start: 0, end: 1 },
      { id: "Inner", name: "Inner", mode: "auto", parent: "Group", depth: 1, start: 1, end: 1 },
    ],
    cells: [
      { row: 0, col: 1, variables: ["a"], feedback: false },
      { row: 1, col: 2, variables: ["b"], feedback: false },
      { row: 2, col: 0, variables: ["c"], feedback: true },
      { row: 0, col: 2, variables: ["a2"], feedback: false },
    ],
  };
}

test("nothing collapsed: the view is the data", () => {
  const view = collapse(data(), new Set());
  assert.deepEqual(
    view.entries.map((entry) => entry.id),
    ["A", "B", "C"],
  );
  assert.equal(view.cells.length, 4);
  assert.deepEqual(
    view.blocks.map((block) => [block.id, block.start, block.end]),
    [
      ["Group", 0, 1],
      ["Inner", 1, 1],
    ],
  );
});

test("collapsing a block merges its rows and columns", () => {
  const view = collapse(data(), new Set(["Group"]));
  assert.deepEqual(
    view.entries.map((entry) => [entry.id, entry.collapsed]),
    [
      ["Group", true],
      ["C", false],
    ],
  );
  // A -> B is inside the block; A -> C and B -> C merge.
  assert.deepEqual(view.cells, [
    { row: 0, col: 1, variables: ["a2", "b"], feedback: false, links: [] },
    { row: 1, col: 0, variables: ["c"], feedback: true, links: [] },
  ]);
  assert.deepEqual(view.blocks, []);
});

test("inner blocks of a collapsed block are ignored", () => {
  const view = collapse(data(), new Set(["Group", "Inner"]));
  assert.deepEqual(
    view.entries.map((entry) => entry.id),
    ["Group", "C"],
  );
});

test("collapsing an inner block keeps the outer one", () => {
  const view = collapse(data(), new Set(["Inner"]));
  assert.deepEqual(
    view.entries.map((entry) => entry.id),
    ["A", "Inner", "C"],
  );
  assert.deepEqual(
    view.blocks.map((block) => [block.id, block.start, block.end]),
    [["Group", 0, 1]],
  );
});

test("cells by row are sorted by column", () => {
  const rows = cellsByRow(data().cells);
  assert.deepEqual(
    rows.get(0).map((cell) => cell.col),
    [1, 2],
  );
});

test("siblings and reordering stay within a container", () => {
  const view = collapse(data(), new Set());
  assert.deepEqual(siblings(view, "root"), [
    { id: "Group", start: 0, end: 1 },
    { id: "C", start: 2, end: 2 },
  ]);
  // Dragging C onto the Group block puts it first.
  assert.deepEqual(reorder(view, 2, 1), { parent: "root", ids: ["C", "Group"] });
  // B stands inside the Inner block, a sibling of A in Group.
  assert.deepEqual(reorder(view, 0, 1), { parent: "Group", ids: ["Inner", "A"] });
  // Dropping A on C (outside Group) changes nothing.
  assert.equal(reorder(view, 0, 2), null);
  assert.equal(reorder(view, 2, 2), null);
});

test("dragging down puts the entry after the target", () => {
  const entry = (id) => ({ id, name: id, type: "component", kind: "", parent: "root", depth: 0 });
  const view = collapse({ level: "root", entries: ["A", "B", "C"].map(entry), blocks: [], cells: [] }, new Set());
  assert.deepEqual(reorder(view, 0, 1), { parent: "root", ids: ["B", "A", "C"] });
  assert.deepEqual(reorder(view, 0, 2), { parent: "root", ids: ["B", "C", "A"] });
  assert.deepEqual(reorder(view, 2, 0), { parent: "root", ids: ["C", "A", "B"] });
});
