import assert from "node:assert/strict";
import { test } from "node:test";

import { nodeAppearance } from "../../gemseo_process_builder/static/js/lib/node_icons.js";
import { dependencyOrder, orderAfter } from "../../gemseo_process_builder/static/js/lib/chain_order.js";
import { fromSnapshot } from "../../gemseo_process_builder/static/js/lib/patch.js";
import { TERMINAL_GAP, buildScene, levelsToResolve, topLevelRects } from "../../gemseo_process_builder/static/js/lib/scene.js";

/** A model with an optimizer driving two components, next to a component of the root. */
function tileState() {
  return fromSnapshot({
    rev: 1,
    root: "n-root",
    nodes: {
      "n-root": { id: "n-root", name: "Model", type: "assembly", parent: null, children: ["n-opt", "n-post"] },
      "n-opt": {
        id: "n-opt",
        name: "Optimizer",
        type: "driver",
        kind: "optimization",
        parent: "n-root",
        children: ["n-aero", "n-perf"],
        config: { design_space: [{ variable: "area" }], objectives: [{ variable: "range" }] },
      },
      "n-aero": { id: "n-aero", name: "Aero", type: "component", parent: "n-opt", ports: [] },
      "n-perf": { id: "n-perf", name: "Perf", type: "component", parent: "n-opt", ports: [] },
      "n-post": { id: "n-post", name: "Post", type: "component", parent: "n-root", ports: [] },
    },
    links: {},
    layout: {
      "n-opt": { x: 0, y: 100 },
      "n-aero": { x: 300, y: 0 },
      "n-perf": { x: 600, y: 0 },
      "n-post": { x: 900, y: 0 },
    },
    levels: {},
    view: {},
    project: {},
  });
}

function tileViews() {
  return new Map([
    ["n-root", { level: "n-root", ports: { "n-opt": { in: [], out: ["range"] } }, edges: [], free_inputs: [] }],
    [
      "n-opt",
      {
        level: "n-opt",
        ports: { "n-aero": { in: { a: "area" }, out: { d: "drag" } }, "n-perf": { in: { d: "drag" }, out: { r: "range" } } },
        edges: [
          {
            source: "n-aero",
            target: "n-perf",
            feedback: false,
            variables: [{ name: "drag", source_port: "d", target_port: "d", explicit: false }],
          },
        ],
        free_inputs: [],
      },
    ],
  ]);
}

test("the nodes of an assembly run as a chain show their rank", () => {
  const state = tileState();
  state.nodes["n-opt"] = { ...state.nodes["n-opt"], type: "assembly", mode: "chain" };
  state.layout["n-opt"] = { ...state.layout["n-opt"], expanded: true };
  const scene = buildScene(state, "n-root", new Map(), tileViews());
  assert.deepEqual(
    scene.items.filter((item) => item.order).map((item) => `${item.id}:${item.order}`),
    ["n-aero:1", "n-perf:2"],
  );
  assert.equal(nodeAppearance(state.nodes["n-opt"]).label, "Assembly · chain, in order");
  assert.equal(nodeAppearance({ type: "assembly", mode: "auto" }).label, "Assembly");
});

test("a chain shows an execution arrow from each node to the next", () => {
  const state = tileState();
  state.nodes["n-opt"] = { ...state.nodes["n-opt"], type: "assembly", mode: "chain" };
  state.layout["n-opt"] = { ...state.layout["n-opt"], expanded: true };
  const scene = buildScene(state, "n-root", new Map(), tileViews());
  const arrows = scene.links.filter((link) => link.kind === "execution");
  assert.deepEqual(
    arrows.map((link) => `${link.from}>${link.to}`),
    ["n-aero>n-perf"],
  );
  assert.equal(arrows[0].container, "n-opt");
  assert.match(arrows[0].mark ?? "", /Z$/); // The arrowhead.
  // Seen from inside, the level itself is the chain.
  const inside = buildScene(state, "n-opt", new Map(), tileViews());
  assert.equal(inside.links.filter((link) => link.kind === "execution").length, 1);
});

test("a parallel block forks to its nodes and joins them", () => {
  const state = tileState();
  state.nodes["n-opt"] = { ...state.nodes["n-opt"], type: "assembly", mode: "parallel" };
  state.layout["n-opt"] = { ...state.layout["n-opt"], expanded: true };
  const scene = buildScene(state, "n-root", new Map(), tileViews());
  const arrows = scene.links.filter((link) => link.kind === "execution").map((link) => `${link.from}>${link.to}`);
  assert.deepEqual(arrows, ["n-opt>n-aero", "n-aero>n-opt", "n-opt>n-perf", "n-perf>n-opt"]);
});

test("an arrow drawn to a node makes it run right after", () => {
  assert.deepEqual(orderAfter(["a", "b", "c", "d"], "a", "d"), ["a", "d", "b", "c"]);
  assert.deepEqual(orderAfter(["a", "b", "c"], "c", "a"), ["b", "c", "a"]);
  assert.deepEqual(orderAfter(["a", "b"], "a", "b"), ["a", "b"]);
});

test("a chain made from a group starts from the order of the dependencies", () => {
  const edges = [
    { source: "c", target: "a" },
    { source: "a", target: "b" },
  ];
  assert.deepEqual(dependencyOrder(["a", "b", "c", "d"], edges), ["c", "a", "b", "d"]);
  // A loop keeps the order of the list.
  assert.deepEqual(dependencyOrder(["a", "b"], [{ source: "a", target: "b" }, { source: "b", target: "a" }]), ["a", "b"]);
});

/** The inputs and outputs of tileState()'s model. */
const IO = {
  inputs: [{ name: "load", nodes: ["n-aero"], value: 3, text: "3", unit: null, final: false }],
  outputs: [
    { name: "range", nodes: ["n-perf"], value: null, text: null, unit: null, final: true },
    { name: "cost", nodes: ["n-post"], value: null, text: null, unit: null, final: true },
  ],
  others: [],
};

test("a driver is a container: the nodes it drives are inside it", () => {
  const state = tileState();
  assert.deepEqual(levelsToResolve(state, "n-root"), ["n-root"]);
  const scene = buildScene(state, "n-root", new Map(), tileViews());
  assert.deepEqual(
    scene.items.map((item) => item.id),
    ["n-opt", "n-post"],
  );
  assert.ok(scene.items[0].container);
  // Expanded in place, like an assembly.
  state.layout["n-opt"] = { ...state.layout["n-opt"], expanded: true };
  const expanded = buildScene(state, "n-root", new Map(), tileViews());
  assert.deepEqual(expanded.items.find((item) => item.id === "n-aero")?.depth, 1);
});

test("the start and the end of a workflow are circles linked to its nodes", () => {
  const scene = buildScene(tileState(), "n-root", new Map(), tileViews(), false, IO);
  const start = scene.items.find((item) => item.terminal === "start");
  const end = scene.items.find((item) => item.terminal === "end");
  assert.ok(start && end);
  assert.equal(start.x + start.width + TERMINAL_GAP, 0); // On the left of the nodes.
  assert.equal(end.x, 900 + 210 + TERMINAL_GAP); // On the right of Post.
  const io = scene.links.filter((link) => link.kind === "io").map((link) => `${link.from}>${link.to}`);
  // The components of the optimizer are inside it: its card stands for them.
  assert.deepEqual(io, ["start:n-root>n-opt", "n-opt>end:n-root", "n-post>end:n-root"]);
  assert.equal(scene.box?.x, start.x); // Fitting shows them.
  // They are not nodes: a rectangle selection leaves them out.
  assert.ok(![...topLevelRects(scene.items).keys()].some((id) => id.includes(":")));
});

test("a chain goes from the start to the end", () => {
  const state = tileState();
  state.nodes["n-root"] = { ...state.nodes["n-root"], mode: "chain" };
  const scene = buildScene(state, "n-root", new Map(), tileViews(), false, IO);
  const arrows = scene.links.filter((link) => link.kind === "execution").map((link) => `${link.from}>${link.to}`);
  assert.deepEqual(arrows, ["n-opt>n-post", "start:n-root>n-opt", "n-post>end:n-root"]);
  // Above the first node and under the last one: the arrows go straight.
  const start = scene.items.find((item) => item.terminal === "start");
  const opt = scene.items.find((item) => item.id === "n-opt");
  assert.ok(start && opt && start.x + start.width / 2 === opt.x + opt.width / 2 && start.y < opt.y);
});
