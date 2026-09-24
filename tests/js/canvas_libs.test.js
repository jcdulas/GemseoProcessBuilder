import assert from "node:assert/strict";
import { test } from "node:test";

import {
  HEADER_HEIGHT,
  NODE_WIDTH,
  PORT_ROW_HEIGHT,
  boundingBox,
  fitText,
  fitTransform,
  gridPosition,
  linkPath,
  nodeShape,
  portAnchor,
  visiblePorts,
} from "../../gemseo_process_builder/static/js/lib/geometry.js";
import { rectFromCorners, selectInRect } from "../../gemseo_process_builder/static/js/lib/hit_test.js";
import { fromSnapshot } from "../../gemseo_process_builder/static/js/lib/patch.js";
import { buildScene, connectedPorts } from "../../gemseo_process_builder/static/js/lib/scene.js";

const ports = [
  { local_name: "x", direction: "in" },
  { local_name: "y", direction: "in" },
  { local_name: "z", direction: "out" },
];

test("port display modes", () => {
  assert.deepEqual(visiblePorts(ports, "all", new Set()), { inputs: ["x", "y"], outputs: ["z"], hidden: 0 });
  assert.deepEqual(visiblePorts(ports, "connected", new Set(["in:y"])), {
    inputs: ["y"],
    outputs: [],
    hidden: 2,
  });
  assert.deepEqual(visiblePorts(ports, "none", new Set()), { inputs: [], outputs: [], hidden: 3 });
});

test("node height grows with the port rows", () => {
  const empty = nodeShape({ inputs: [], outputs: [], hidden: 0 });
  const two = nodeShape({ inputs: ["x", "y"], outputs: ["z"], hidden: 0 });
  const hidden = nodeShape({ inputs: ["x", "y"], outputs: ["z"], hidden: 1 });
  assert.ok(empty.height > HEADER_HEIGHT);
  assert.equal(hidden.height - two.height, PORT_ROW_HEIGHT);
  assert.equal(two.width, NODE_WIDTH);
  assert.ok(two.inputs[1].y > two.inputs[0].y);
});

test("port anchors are on the sides", () => {
  const shape = nodeShape({ inputs: ["x"], outputs: ["z"], hidden: 0 });
  assert.deepEqual(portAnchor({ x: 10, y: 20 }, shape, "in", "x"), { x: 10, y: 20 + shape.inputs[0].y });
  assert.equal(portAnchor({ x: 10, y: 20 }, shape, "out", "z")?.x, 10 + NODE_WIDTH);
  assert.equal(portAnchor({ x: 0, y: 0 }, shape, "in", "nope"), null);
});

test("link paths start and end at the anchors", () => {
  const path = linkPath({ x: 0, y: 5 }, { x: 100, y: 50 });
  assert.ok(path.startsWith("M0,5 C"));
  assert.ok(path.endsWith(" 100,50"));
});

test("bounding box and fit", () => {
  const box = boundingBox([
    { x: 0, y: 0, width: 10, height: 10 },
    { x: 100, y: 50, width: 20, height: 20 },
  ]);
  assert.deepEqual(box, { x: 0, y: 0, width: 120, height: 70 });
  assert.equal(boundingBox([]), null);
  const transform = fitTransform(box, { width: 1000, height: 800 }, { padding: 0, maxScale: 100 });
  assert.equal(transform.k, Math.min(1000 / 120, 800 / 70));
  assert.equal(transform.x + transform.k * 60, 500);
  assert.deepEqual(fitTransform(null, { width: 10, height: 10 }), { x: 0, y: 0, k: 1 });
});

test("grid positions and text fitting", () => {
  assert.deepEqual(gridPosition(0), { x: 40, y: 40 });
  assert.ok(gridPosition(4).y > gridPosition(3).y);
  assert.equal(fitText("short", 200), "short");
  assert.ok(fitText("a very long name indeed", 50).endsWith("…"));
});

test("rectangle selection", () => {
  const rects = new Map([
    ["a", { x: 0, y: 0, width: 10, height: 10 }],
    ["b", { x: 50, y: 50, width: 10, height: 10 }],
  ]);
  const area = rectFromCorners({ x: 55, y: 55 }, { x: 5, y: 5 });
  assert.deepEqual(area, { x: 5, y: 5, width: 50, height: 50 });
  assert.deepEqual(selectInRect(area, rects), ["a", "b"]);
  assert.deepEqual(selectInRect(area, rects, "contain"), []);
});

function sceneState() {
  return fromSnapshot({
    rev: 1,
    root: "n-root",
    nodes: {
      "n-root": { id: "n-root", name: "Model", type: "assembly", parent: null, children: ["n-a", "n-g"] },
      "n-a": { id: "n-a", name: "A", type: "component", parent: "n-root", ports: [{ local_name: "y", direction: "out" }] },
      "n-g": { id: "n-g", name: "G", type: "assembly", parent: "n-root", children: ["n-b"] },
      "n-b": { id: "n-b", name: "B", type: "component", parent: "n-g", ports: [{ local_name: "y", direction: "in" }] },
    },
    links: { "l-1": { id: "l-1", source: { node: "n-a", port: "y" }, target: { node: "n-b", port: "y" } } },
    layout: { "n-a": { x: 0, y: 0 }, "n-g": { x: 400, y: 0 }, "n-b": { x: 10, y: 10 } },
    levels: {},
    view: {},
    project: {},
  });
}

test("a collapsed container stands for its children", () => {
  const scene = buildScene(sceneState(), "n-root");
  assert.deepEqual(scene.items.map((item) => item.id), ["n-a", "n-g"]);
  assert.equal(scene.links.length, 1);
  assert.equal(scene.links[0].to, "n-g");
});

test("an expanded container shows its children inside", () => {
  const state = sceneState();
  state.layout["n-g"].expanded = true;
  const scene = buildScene(state, "n-root");
  const group = scene.items.find((item) => item.id === "n-g");
  const child = scene.items.find((item) => item.id === "n-b");
  assert.ok(child && group);
  assert.equal(child.depth, 1);
  assert.ok(child.x > group.x && child.x + child.width <= group.x + group.width);
  assert.equal(scene.links[0].to, "n-b");
  assert.deepEqual(child.local, { x: 10, y: 10 });
});

test("drag overrides replace stored positions", () => {
  const scene = buildScene(sceneState(), "n-root", new Map([["n-a", { x: 99, y: 7 }]]));
  const item = scene.items.find((candidate) => candidate.id === "n-a");
  assert.equal(item?.x, 99);
});

test("nodes without a position get grid positions", () => {
  const state = sceneState();
  delete state.layout["n-a"];
  const scene = buildScene(state, "n-root");
  assert.deepEqual(scene.items[0].local, gridPosition(0));
});

test("connected ports come from links", () => {
  const connected = connectedPorts(sceneState().links);
  assert.deepEqual([...(connected.get("n-a") ?? [])], ["out:y"]);
  assert.deepEqual([...(connected.get("n-b") ?? [])], ["in:y"]);
});
