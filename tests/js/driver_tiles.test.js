import assert from "node:assert/strict";
import { test } from "node:test";

import { driverLinks, driverVariables } from "../../gemseo_process_builder/static/js/lib/driver_links.js";
import { nodeAppearance } from "../../gemseo_process_builder/static/js/lib/node_icons.js";
import { dependencyOrder, orderAfter } from "../../gemseo_process_builder/static/js/lib/chain_order.js";
import { fromSnapshot } from "../../gemseo_process_builder/static/js/lib/patch.js";
import { TILE_GAP, buildScene, levelsToResolve } from "../../gemseo_process_builder/static/js/lib/scene.js";

const CONFIG = {
  design_space: [{ variable: "area" }, { variable: "span" }],
  objectives: [{ variable: "range" }],
  constraints: [{ variable: "loading" }],
  observables: ["weight"],
  responses: ["drag"],
  levels: [{ variable: "span" }],
};

test("each kind of driver sends and gets back its own variables", () => {
  const roles = (/** @type {{name: string, role: string}[]} */ items) => items.map((item) => `${item.name}:${item.role}`);
  const optimization = driverVariables("optimization", CONFIG);
  assert.deepEqual(roles(optimization.sent), ["area:design variable", "span:design variable"]);
  assert.deepEqual(roles(optimization.received), ["range:objective", "loading:constraint", "weight:observable"]);
  assert.deepEqual(roles(driverVariables("doe", CONFIG).received), ["drag:response", "weight:observable"]);
  assert.deepEqual(roles(driverVariables("parametric", CONFIG).sent), ["span:parameter"]);
  assert.deepEqual(driverVariables("mda", CONFIG), { sent: [], received: [] });
  assert.deepEqual(driverVariables("optimization", undefined), { sent: [], received: [] });
});

/** The scope of an optimizer: Aero uses the design variables, Performance gives the objective. */
const VIEW = {
  ports: {
    "n-aero": { in: { S: "area", b: "span" }, out: { D: "drag" } },
    "n-perf": { in: { D: "drag" }, out: { R: "range", L: "loading" } },
    "n-log": { in: { t: "time" }, out: {} },
    "n-group": { in: ["span"], out: ["weight"] },
  },
};

test("a driver sends its design variables and gets its results back", () => {
  const driver = { id: "n-opt", kind: "optimization", config: CONFIG, children: ["n-aero", "n-perf", "n-log", "n-group"] };
  const links = driverLinks(driver, VIEW);
  const summary = links.map(
    (link) => `${link.source}>${link.target}:${link.variables.map((variable) => variable.name).join(",")}${link.control ? " control" : ""}`,
  );
  assert.deepEqual(summary, [
    "n-opt>n-aero:area,span",
    "n-perf>n-opt:range,loading",
    "n-opt>n-log: control",
    "n-opt>n-group:span",
    "n-group>n-opt:weight",
  ]);
  // Before its scope is resolved, the driver drives its nodes without variables.
  assert.ok(driverLinks(driver, undefined).every((link) => link.control));
});

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

test("a driver is a tile, with the nodes it drives at the same level", () => {
  const state = tileState();
  assert.deepEqual(levelsToResolve(state, "n-root"), ["n-root", "n-opt"]);
  const scene = buildScene(state, "n-root", new Map(), tileViews());
  const byId = new Map(scene.items.map((item) => [item.id, item]));
  assert.deepEqual([...byId.keys()], ["n-opt", "n-aero", "n-perf", "n-post"]);
  assert.ok(byId.get("n-opt")?.tile);
  assert.ok(!byId.get("n-opt")?.expanded);
  // Same coordinates as the level, and at its depth: selectable like the others.
  assert.deepEqual([byId.get("n-aero")?.x, byId.get("n-aero")?.depth, byId.get("n-aero")?.parent], [300, 0, "n-opt"]);
  const links = scene.links.map((link) => `${link.kind}:${link.from}>${link.to}`);
  assert.deepEqual(links, ["implicit:n-aero>n-perf", "driver:n-opt>n-aero", "driver:n-perf>n-opt"]);
  const back = scene.links.find((link) => link.to === "n-opt");
  assert.equal(back?.driver, "n-opt");
  assert.match(back?.path ?? "", / V/); // Loops under the nodes, back to the tile.
  assert.equal(scene.box?.x, 0);
});

test("a tile over the nodes it drives is shown on their left", () => {
  const state = tileState();
  state.layout["n-opt"] = { x: 400, y: 0 };
  const scene = buildScene(state, "n-root", new Map(), tileViews());
  const tile = scene.items.find((item) => item.id === "n-opt");
  assert.ok(tile);
  assert.equal(tile.x + tile.width + TILE_GAP, 300);
  assert.deepEqual(tile.local, { x: tile.x, y: tile.y });
  // Dragged, it goes where the pointer takes it.
  const dragged = buildScene(state, "n-root", new Map([["n-opt", { x: 420, y: 0 }]]), tileViews());
  assert.equal(dragged.items.find((item) => item.id === "n-opt")?.x, 420);
});

test("nested drivers are tiles too", () => {
  const state = tileState();
  state.nodes["n-inner"] = {
    id: "n-inner",
    name: "Inner",
    type: "driver",
    kind: "mda",
    parent: "n-opt",
    children: ["n-sub"],
  };
  state.nodes["n-sub"] = { id: "n-sub", name: "Sub", type: "component", parent: "n-inner", ports: [] };
  state.nodes["n-opt"].children.push("n-inner");
  state.layout["n-inner"] = { x: 300, y: 300 };
  state.layout["n-sub"] = { x: 600, y: 300 };
  assert.deepEqual(levelsToResolve(state, "n-root"), ["n-root", "n-opt", "n-inner"]);
  const scene = buildScene(state, "n-root", new Map(), tileViews());
  assert.ok(scene.items.find((item) => item.id === "n-inner")?.tile);
  assert.equal(scene.items.find((item) => item.id === "n-sub")?.depth, 0);
  const control = scene.links.find((link) => link.from === "n-inner");
  assert.equal(control?.kind, "control");
});

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
