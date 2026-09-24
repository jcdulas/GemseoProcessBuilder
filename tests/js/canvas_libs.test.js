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
import { linkCompatibility } from "../../gemseo_process_builder/static/js/lib/link_compat.js";
import { feedbackPath, routeLink } from "../../gemseo_process_builder/static/js/lib/link_routing.js";
import { buildScene, connectedPorts, levelsToResolve } from "../../gemseo_process_builder/static/js/lib/scene.js";

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

/** Level views as returned by resolve.levels for sceneState(). */
function sceneViews() {
  return new Map([
    [
      "n-root",
      {
        level: "n-root",
        ports: { "n-a": { in: {}, out: { y: "y" } }, "n-g": { in: ["y"], out: [] } },
        edges: [
          {
            source: "n-a",
            target: "n-g",
            feedback: false,
            variables: [{ name: "y", source_port: "y", target_port: "", explicit: true }],
          },
        ],
        free_inputs: [],
      },
    ],
    [
      "n-g",
      { level: "n-g", ports: { "n-b": { in: { y: "y" }, out: {} } }, edges: [], free_inputs: ["y"] },
    ],
  ]);
}

test("a collapsed container shows derived ports and stands for its children", () => {
  const scene = buildScene(sceneState(), "n-root", new Map(), sceneViews());
  assert.deepEqual(scene.items.map((item) => item.id), ["n-a", "n-g"]);
  const group = scene.items.find((item) => item.id === "n-g");
  assert.deepEqual(group?.shape.inputs.map((row) => row.name), ["y"]);
  assert.equal(scene.links.length, 1);
  assert.equal(scene.links[0].to, "n-g");
  assert.equal(scene.links[0].kind, "explicit");
  assert.equal(scene.links[0].targetPort, "y");
});

test("an expanded container shows its children inside", () => {
  const state = sceneState();
  state.layout["n-g"].expanded = true;
  const scene = buildScene(state, "n-root", new Map(), sceneViews());
  const group = scene.items.find((item) => item.id === "n-g");
  const child = scene.items.find((item) => item.id === "n-b");
  assert.ok(child && group);
  assert.equal(child.depth, 1);
  assert.ok(child.x > group.x && child.x + child.width <= group.x + group.width);
  assert.deepEqual(child.local, { x: 10, y: 10 });
  assert.deepEqual([...child.freeInputs], ["y"]);
  assert.deepEqual(levelsToResolve(state, "n-root"), ["n-root", "n-g"]);
});

test("many variables between two nodes make one aggregated link", () => {
  const views = sceneViews();
  const variables = ["a", "b", "c", "d", "e"].map((name) => ({ name, source_port: name, target_port: "", explicit: false }));
  views.get("n-root").edges[0].variables = variables;
  const scene = buildScene(sceneState(), "n-root", new Map(), views);
  assert.equal(scene.links.length, 1);
  assert.equal(scene.links[0].kind, "aggregated");
  assert.ok(scene.links[0].label);
});

test("feedback links go around", () => {
  const views = sceneViews();
  views.get("n-root").edges[0].feedback = true;
  const scene = buildScene(sceneState(), "n-root", new Map(), views);
  assert.ok(scene.links[0].feedback);
  assert.match(scene.links[0].path, / V/);
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

test("connected ports come from the resolved couplings", () => {
  const connected = connectedPorts([...sceneViews().values()]);
  assert.deepEqual([...(connected.get("n-a") ?? [])], ["out:y"]);
  assert.deepEqual([...(connected.get("n-g") ?? [])], ["in:y"]);
});

test("link compatibility", () => {
  assert.equal(linkCompatibility({ dtype: "float", shape: [1] }, { dtype: "float", shape: [] }).ok, true);
  assert.equal(linkCompatibility({ dtype: "str" }, { dtype: "float" }).ok, false);
  assert.equal(linkCompatibility({ dtype: "int" }, { dtype: "float" }).ok, true);
  assert.equal(linkCompatibility({ dtype: "float" }, { dtype: "int" }).ok, false);
  assert.match(linkCompatibility({ shape: [3] }, { shape: [2] }).reason, /sizes differ/);
  assert.ok(linkCompatibility({ shape: [3], shape_known: false }, { shape: [2] }).warning);
  assert.equal(linkCompatibility({ dtype: "object" }, { dtype: "str" }).ok, true);
});

test("routing: forward curves, feedback detours below the nodes", () => {
  assert.match(routeLink({ x: 0, y: 0 }, { x: 100, y: 0 }, { feedback: false, bottom: 50 }), /^M0,0 C/);
  const back = feedbackPath({ x: 200, y: 10 }, { x: 0, y: 10 }, 60);
  assert.ok(back.includes("V78") || back.includes("88"));
  assert.ok(back.endsWith("H0"));
});
