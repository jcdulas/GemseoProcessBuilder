import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_FILTER,
  applyFilter,
  describeFilter,
  needsRanking,
  rankingQuery,
} from "../../gemseo_process_builder/static/js/lib/results_filter.js";
import {
  contourIndex,
  gridRange,
  interpolate,
  isoSegments,
  project,
  surfaceCells,
  valueAt,
} from "../../gemseo_process_builder/static/js/lib/surface_3d.js";

const COLUMNS = [
  { name: "x[0]", role: "design variable" },
  { name: "x[1]", role: "design variable" },
  { name: "x[2]", role: "design variable" },
  { name: "g[0]", role: "constraint" },
  { name: "g[1]", role: "constraint" },
  { name: "f", role: "objective" },
  { name: "feasible", role: "feasibility" },
];

/** @type {import("../../gemseo_process_builder/static/js/lib/results_filter.js").Ranking} */
const RANKING = {
  method: "gradient",
  response: "f",
  evaluation: 40,
  note: "",
  inputs: [
    { name: "x[2]", score: 3, bound: "upper" },
    { name: "x[0]", score: 2, bound: null },
    { name: "x[1]", score: 1, bound: null },
  ],
  responses: [
    { name: "f", role: "objective", value: 1, status: null },
    { name: "g[1]", role: "constraint", value: 0.5, status: "violated" },
    { name: "g[0]", role: "constraint", value: -2, status: "satisfied" },
  ],
  total_inputs: 3,
  total_responses: 3,
  at_bounds: 1,
};

test("all the variables, the objective first, without asking the worker", () => {
  assert.equal(needsRanking(DEFAULT_FILTER), false);
  const result = applyFilter(COLUMNS, DEFAULT_FILTER, null);
  assert.deepEqual(result.inputs, ["x[0]", "x[1]", "x[2]"]);
  assert.deepEqual(result.responses, ["f", "g[0]", "g[1]"]);
  assert.equal(describeFilter(DEFAULT_FILTER, result, null), "3 design variables");
});

test("the largest gradients, and the constraints in the order of the ranking", () => {
  const state = { ...DEFAULT_FILTER, mode: /** @type {const} */ ("gradient"), count: 2 };
  assert.deepEqual(rankingQuery(state), { method: "gradient", response: "", limit: 2, active_only: false, response_limit: 500 });
  const result = applyFilter(COLUMNS, state, RANKING);
  assert.deepEqual(result.inputs, ["x[2]", "x[0]"]);
  assert.deepEqual(result.responses, ["f", "g[1]", "g[0]"]);
  assert.equal(result.bounds.get("x[2]"), "upper");
  assert.equal(
    describeFilter(state, result, RANKING),
    "2 of 3 design variables, largest gradients of f × range · 0 active and 1 violated constraints · at the best evaluation (40)",
  );
});

test("the active set: variables at a bound, active and violated constraints", () => {
  const state = { ...DEFAULT_FILTER, mode: /** @type {const} */ ("active"), constraints: /** @type {const} */ ("active") };
  assert.equal(rankingQuery(state).active_only, true);
  const result = applyFilter(COLUMNS, state, RANKING);
  assert.deepEqual(result.inputs, ["x[2]"]);
  assert.deepEqual(result.responses, ["f", "g[1]"]);
  // Only the constraints: every design variable.
  const constraintsOnly = applyFilter(COLUMNS, { ...DEFAULT_FILTER, constraints: "active" }, RANKING);
  assert.deepEqual(constraintsOnly.inputs, ["x[0]", "x[1]", "x[2]"]);
  assert.equal(rankingQuery({ ...DEFAULT_FILTER, constraints: "active" }).limit, 0);
});

test("a point of the unit box seen from the front and from above", () => {
  const front = { azimuth: 0, elevation: 0 };
  assert.deepEqual(project(front, 1, 0.5, 0.5), { x: 0.5, y: -0, depth: 0 });
  const above = project({ azimuth: 0, elevation: Math.PI / 2 }, 0.5, 1, 0.5);
  assert.ok(Math.abs(above.y + 0.5) < 1e-12); // The far edge at the top of the screen.
  // Turned a quarter: x goes away from the viewer.
  assert.ok(Math.abs(project({ azimuth: Math.PI / 2, elevation: 0 }, 1, 0.5, 0.5).depth - 0.5) < 1e-12);
});

test("surface cells from the farthest to the nearest, holes left out", () => {
  const grid = [
    [0, 1, 2],
    [1, 2, null],
    [2, 3, 4],
  ];
  assert.deepEqual(gridRange(grid), [0, 4]);
  assert.deepEqual(gridRange([[3, 3]]), [2.5, 3.5]);
  const cells = surfaceCells(grid, { azimuth: 0, elevation: 0.5 });
  // Two cells touch the hole; the one farther along y comes first.
  assert.deepEqual(
    cells.map((cell) => cell.value),
    [2, 1],
  );
  const full = surfaceCells(
    [
      [0, 0],
      [0, 0],
      [0, 0],
    ],
    { azimuth: 0, elevation: 0.5 },
  );
  assert.ok(full[0].depth > full[1].depth);
});

test("interpolation, contour coordinates and axis values", () => {
  const grid = [
    [0, 2],
    [2, 4],
  ];
  assert.equal(interpolate(grid, 0.5, 0.5), 2);
  assert.equal(interpolate(grid, 1, 0), 2);
  assert.equal(interpolate([[0, null], [1, 1]], 0.2, 0.2), null);
  assert.equal(contourIndex(0, 10), 0);
  assert.equal(contourIndex(3.5, 10), 3);
  assert.equal(contourIndex(10, 10), 9);
  assert.equal(valueAt([10, 20, 30], 1.5), 25);
});

test("the line where a grid crosses a level", () => {
  // Zero between the first and second columns: a vertical line at i = 0.5.
  const segments = isoSegments(
    [
      [-1, 1, 3],
      [-1, 1, 3],
    ],
    0,
  );
  assert.deepEqual(segments, [
    [
      [0.5, 0],
      [0.5, 1],
    ],
  ]);
  // A saddle gives two segments; a flat grid none.
  assert.equal(isoSegments([[1, -1], [-1, 1]], 0).length, 2);
  assert.equal(isoSegments([[1, 1], [1, 1]], 0).length, 0);
});
