import assert from "node:assert/strict";
import { test } from "node:test";

import { freeSpot, portId, positionsFromElk, toElkGraph } from "../../gemseo_process_builder/static/js/lib/elk_graph.js";

const shape = (inputs, outputs) => ({
  width: 200,
  height: 80,
  inputs: inputs.map((name, index) => ({ name, y: 40 + index * 18 })),
  outputs: outputs.map((name, index) => ({ name, y: 40 + index * 18 })),
  hidden: 0,
});

const items = [
  { id: "A", width: 200, height: 80, shape: shape(["y2"], ["y1"]), local: { x: 100, y: 50 } },
  { id: "B", width: 200, height: 80, shape: shape(["y1"], ["y2"]), local: { x: 500, y: 300 } },
];

test("nodes with their ports at fixed positions", () => {
  const graph = toElkGraph(items, []);
  const a = graph.children[0];
  assert.equal(a.layoutOptions["elk.portConstraints"], "FIXED_POS");
  assert.deepEqual(
    a.ports.map((port) => [port.id, port.x, port.y, port.layoutOptions["elk.port.side"]]),
    [
      ["A|in|y2", 0, 40, "WEST"],
      ["A|out|y1", 199, 40, "EAST"],
    ],
  );
  assert.equal(graph.layoutOptions["elk.direction"], "RIGHT");
});

test("links become edges between ports, feedbacks included", () => {
  const links = [
    { id: "l1", from: "A", to: "B", sourcePort: "y1", targetPort: "y1" },
    // A feedback: ELK breaks the cycle itself.
    { id: "l2", from: "B", to: "A", sourcePort: "y2", targetPort: "y2" },
    // A port that is not shown: the edge joins the nodes.
    { id: "l3", from: "A", to: "B", sourcePort: "hidden", targetPort: "y1" },
    // Links to nodes outside the laid out ones are left out.
    { id: "l4", from: "A", to: "C", sourcePort: "y1", targetPort: "y1" },
  ];
  const graph = toElkGraph(items, links);
  assert.deepEqual(
    graph.edges.map((edge) => [edge.sources[0], edge.targets[0]]),
    [
      [portId("A", "out", "y1"), portId("B", "in", "y1")],
      [portId("B", "out", "y2"), portId("A", "in", "y2")],
      ["A", portId("B", "in", "y1")],
    ],
  );
});

test("positions come back where the nodes were", () => {
  const result = { children: [{ id: "A", x: 12, y: 30 }, { id: "B", x: 302, y: 12 }] };
  // The top-left corner of the nodes stays at (100, 50).
  assert.deepEqual(positionsFromElk(result, items), { A: { x: 100, y: 68 }, B: { x: 390, y: 50 } });
  assert.deepEqual(positionsFromElk({ children: [] }, items), {});
});

test("a new node goes to the nearest free place", () => {
  const rects = [{ x: 0, y: 0, width: 200, height: 80 }];
  const size = { width: 200, height: 80 };
  assert.deepEqual(freeSpot(rects, { x: 1000, y: 0 }, size), { x: 1000, y: 0 });
  const spot = freeSpot(rects, { x: 10, y: 10 }, size);
  const clear =
    spot.x >= 230 || spot.x + 230 <= 0 || spot.y >= 110 || spot.y + 110 <= 0;
  assert.ok(clear, JSON.stringify(spot));
});
