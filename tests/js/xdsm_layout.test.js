import assert from "node:assert/strict";
import { test } from "node:test";

import { blockLabel, nodeLabel, processSteps, scenarioName, xdsmLayout } from "../../gemseo_process_builder/static/js/lib/xdsm_layout.js";

/** The XDSM of Sellar MDF, as GEMSEO writes it (shortened). */
const SELLAR = {
  nodes: [
    { id: "Opt", name: "Optimizer", type: "optimization" },
    { id: "Dis1", name: "MDAGaussSeidel", type: "mda" },
    { id: "Dis2", name: "Sellar1", type: "analysis" },
    { id: "Dis3", name: "Sellar2", type: "analysis" },
  ],
  edges: [
    { from: "_U_", to: "Opt", name: "x_1^(0), x_shared^(0)" },
    { from: "Opt", to: "_U_", name: "obj^*" },
    { from: "Opt", to: "Dis2", name: "x_1, x_shared" },
    { from: "Dis2", to: "Dis3", name: "y_1" },
    { from: "Dis3", to: "Dis2", name: "y_2" },
    { from: "Dis3", to: "Opt", name: "c_2, obj" },
    { from: "Dis3", to: "Opt", name: "obj, c_1" },
  ],
  workflow: ["_U_", ["Opt", ["Dis1", ["Dis2", "Dis3"]]]],
};

test("the process loops back to the node driving each loop", () => {
  const steps = processSteps(SELLAR.workflow).map((step) => `${step.from}>${step.to}`);
  assert.deepEqual(steps, ["_U_>Opt", "Opt>Dis1", "Dis1>Dis2", "Dis2>Dis3", "Dis3>Dis1", "Dis1>Opt", "Opt>_U_"]);
});

test("parallel branches start from and return to the same node", () => {
  const steps = processSteps(["_U_", ["Opt", [{ parallel: ["A", "B"] }]]]).map((step) => `${step.from}>${step.to}`);
  assert.deepEqual(steps, ["_U_>Opt", "Opt>A", "Opt>B", "A>Opt", "B>Opt", "Opt>_U_"]);
});

test("components on the diagonal with the steps entering them", () => {
  const layout = xdsmLayout(SELLAR);
  assert.equal(layout.size, 5);
  assert.deepEqual(
    layout.nodes.map((node) => [node.name, node.index, node.steps]),
    [
      ["Optimizer", 1, [1, 6]],
      ["MDAGaussSeidel", 2, [2, 5]],
      ["Sellar1", 3, [3]],
      ["Sellar2", 4, [4]],
    ],
  );
  assert.equal(nodeLabel(layout.nodes[0]), "1, 6: Optimizer");
});

test("data blocks sit in the row of the source and the column of the target", () => {
  const layout = xdsmLayout(SELLAR);
  const cells = layout.blocks.map((block) => [block.row, block.col, block.variables.join(" ")]);
  assert.deepEqual(cells, [
    [0, 1, "x_1^(0) x_shared^(0)"],
    [1, 0, "obj^*"],
    [1, 3, "x_1 x_shared"],
    [3, 4, "y_1"],
    // Two edges with the same variables in another order merge.
    [4, 1, "c_2 obj c_1"],
    [4, 3, "y_2"],
  ]);
});

test("data lines join each component to its blocks", () => {
  const layout = xdsmLayout(SELLAR);
  const lines = layout.lines.map((line) => [line.row1, line.col1, line.row2, line.col2]);
  // Optimizer: row 1 from column 0 to 3, column 1 from row 0 to 4.
  assert.deepEqual(lines.slice(0, 2), [
    [1, 0, 1, 3],
    [0, 1, 4, 1],
  ]);
});

test("labels are shortened and readable", () => {
  assert.equal(blockLabel(["x^(0)", "y^*", "z"]), "x⁰, y*, z");
  assert.equal(blockLabel(["a", "b", "c"], 2), "a, b, …");
  assert.equal(scenarioName("StructureOptimizer_scn-1-3"), "StructureOptimizer");
  assert.equal(scenarioName("Mission"), "Mission");
});
