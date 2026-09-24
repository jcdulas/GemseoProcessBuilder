import assert from "node:assert/strict";
import { test } from "node:test";

import { fromSnapshot } from "../../gemseo_process_builder/static/js/lib/patch.js";
import {
  filterRows,
  formatShape,
  formatValue,
  parseShape,
  parseValue,
  sortRows,
} from "../../gemseo_process_builder/static/js/lib/table_model.js";
import { ancestorsToReveal, flattenTree } from "../../gemseo_process_builder/static/js/lib/tree_flatten.js";
import { scrollToShow, visibleRange } from "../../gemseo_process_builder/static/js/lib/virtual_window.js";

test("visible range with overscan", () => {
  assert.deepEqual(visibleRange({ scrollTop: 0, viewportHeight: 100, rowHeight: 20, count: 1000, overscan: 2 }), {
    first: 0,
    last: 7,
    offset: 0,
    totalHeight: 20000,
  });
  const middle = visibleRange({ scrollTop: 1000, viewportHeight: 100, rowHeight: 20, count: 1000, overscan: 2 });
  assert.equal(middle.first, 48);
  assert.equal(middle.last, 57);
  assert.equal(middle.offset, 960);
  const end = visibleRange({ scrollTop: 1e9, viewportHeight: 100, rowHeight: 20, count: 10, overscan: 2 });
  assert.equal(end.last, 10);
  assert.deepEqual(visibleRange({ scrollTop: 0, viewportHeight: 100, rowHeight: 20, count: 0 }), {
    first: 0,
    last: 0,
    offset: 0,
    totalHeight: 0,
  });
});

test("scrolling to show a row", () => {
  const view = { scrollTop: 100, viewportHeight: 100, rowHeight: 20 };
  assert.equal(scrollToShow(2, view), 40);
  assert.equal(scrollToShow(6, view), null);
  assert.equal(scrollToShow(20, view), 320);
});

function treeState() {
  return fromSnapshot({
    rev: 1,
    root: "r",
    nodes: {
      r: { id: "r", name: "Model", type: "assembly", parent: null, children: ["g", "c"] },
      g: { id: "g", name: "G", type: "assembly", parent: "r", children: ["d"] },
      d: { id: "d", name: "D", type: "component", parent: "g", ports: [] },
      c: {
        id: "c",
        name: "C",
        type: "component",
        parent: "r",
        ports: [
          { local_name: "x", direction: "in" },
          { local_name: "y", direction: "out" },
        ],
      },
    },
    links: {},
    layout: {},
    levels: {},
    view: {},
    project: {},
  });
}

test("collapsed branches are hidden, the root is always open", () => {
  const rows = flattenTree(treeState(), new Set());
  assert.deepEqual(rows.map((row) => row.key), ["r", "g", "c"]);
  assert.deepEqual(rows.map((row) => row.depth), [0, 1, 1]);
});

test("expanded components show their variables", () => {
  const rows = flattenTree(treeState(), new Set(["g", "c"]));
  assert.deepEqual(rows.map((row) => row.key), ["r", "g", "d", "c", "c/in/x", "c/out/y"]);
  assert.equal(rows[4].type, "port");
  assert.equal(rows[2].expandable, false);
});

test("ancestors of a deep node", () => {
  assert.deepEqual(ancestorsToReveal(treeState(), "d"), ["g", "r"]);
});

test("values typed in cells", () => {
  assert.deepEqual(parseValue("1.5"), { value: 1.5, error: null });
  assert.deepEqual(parseValue("-2e-3"), { value: -0.002, error: null });
  assert.deepEqual(parseValue("[1, 2]"), { value: [1, 2], error: null });
  assert.ok(parseValue("[1, 2").error);
  assert.deepEqual(parseValue(""), { value: null, error: null });
  assert.deepEqual(parseValue("abc"), { value: "abc", error: null });
  assert.deepEqual(parseValue("true"), { value: true, error: null });
  assert.equal(formatValue([1, 2]), "[1,2]");
  assert.equal(formatValue(null), "");
});

test("shapes", () => {
  assert.deepEqual(parseShape(""), { value: [], error: null });
  assert.deepEqual(parseShape("3"), { value: [3], error: null });
  assert.deepEqual(parseShape("3x4"), { value: [3, 4], error: null });
  assert.deepEqual(parseShape("2 × 5").value, [2, 5]);
  assert.ok(parseShape("0").error);
  assert.ok(parseShape("abc").error);
  assert.equal(formatShape([]), "scalar");
  assert.equal(formatShape([3, 4]), "3×4");
});

test("sorting is stable and puts empty values last", () => {
  const rows = [{ v: 2, i: 0 }, { v: null, i: 1 }, { v: 1, i: 2 }, { v: 2, i: 3 }];
  assert.deepEqual(sortRows(rows, (row) => row.v, "asc").map((row) => row.i), [2, 0, 3, 1]);
  assert.deepEqual(sortRows(rows, (row) => row.v, "desc").map((row) => row.i), [0, 3, 2, 1]);
});

test("filtering on several values", () => {
  const rows = [{ a: "Alpha", b: "x" }, { a: "Beta", b: "ALPHA-like" }, { a: "Gamma", b: "" }];
  assert.equal(filterRows(rows, "alpha", (row) => [row.a, row.b]).length, 2);
  assert.equal(filterRows(rows, "  ", (row) => [row.a]).length, 3);
});
