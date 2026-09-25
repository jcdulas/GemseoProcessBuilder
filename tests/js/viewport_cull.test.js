import assert from "node:assert/strict";
import { test } from "node:test";

import { contains, cullScene, detailLevel, grow, visibleArea } from "../../gemseo_process_builder/static/js/lib/viewport_cull.js";

test("detail follows the zoom", () => {
  assert.equal(detailLevel(1), "full");
  assert.equal(detailLevel(0.4), "reduced");
  assert.equal(detailLevel(0.2), "outline");
});

test("visible area in scene coordinates", () => {
  assert.deepEqual(visibleArea({ x: -100, y: 50, k: 2 }, 800, 600), { x: 50, y: -25, width: 400, height: 300 });
  assert.deepEqual(grow({ x: 0, y: 0, width: 100, height: 50 }, 0.5), { x: -50, y: -25, width: 200, height: 100 });
  assert.ok(contains({ x: 0, y: 0, width: 10, height: 10 }, { x: 2, y: 2, width: 3, height: 3 }));
  assert.ok(!contains({ x: 0, y: 0, width: 10, height: 10 }, { x: 8, y: 2, width: 3, height: 3 }));
});

/** A grid of items, 20 per row, 200 apart. */
function grid(count) {
  const items = Array.from({ length: count }, (_, index) => ({
    id: `n${index}`,
    x: 200 * (index % 20),
    y: 200 * Math.floor(index / 20),
    width: 150,
    height: 150,
  }));
  const links = items.slice(1).map((item, index) => ({ from: `n${index}`, to: item.id }));
  return { items, links };
}

test("only the items near the area are kept, with their links", () => {
  const { items, links } = cullScene(grid(300), { x: 0, y: 0, width: 390, height: 190 });
  assert.deepEqual(
    items.map((item) => item.id),
    ["n0", "n1"],
  );
  // n0-n1 inside, n1-n2 leaving the area, n19-n20 whose box crosses it.
  assert.deepEqual(
    links.map((link) => link.to),
    ["n1", "n2", "n20"],
  );
});

test("links crossing the area are kept", () => {
  const scene = {
    items: [
      { id: "a", x: 0, y: 0, width: 10, height: 10 },
      { id: "b", x: 1000, y: 0, width: 10, height: 10 },
    ],
    links: [{ from: "a", to: "b" }],
  };
  assert.equal(cullScene(scene, { x: 400, y: -50, width: 100, height: 100 }).links.length, 1);
  assert.equal(cullScene(scene, { x: 400, y: 500, width: 100, height: 100 }).links.length, 0);
});

test("containers of kept items are kept", () => {
  const scene = {
    items: [
      { id: "box", x: 0, y: 0, width: 2000, height: 2000 },
      { id: "inner", x: 1500, y: 1500, width: 100, height: 100, parent: "box" },
      { id: "other", x: 5000, y: 0, width: 100, height: 100 },
    ],
    links: [],
  };
  assert.deepEqual(
    cullScene(scene, { x: 1400, y: 1400, width: 300, height: 300 }).items.map((item) => item.id),
    ["box", "inner"],
  );
});

test("culling a 300-node level with 2,000 links is fast", () => {
  const scene = grid(300);
  for (let index = 0; index < 2000; index += 1) {
    scene.links.push({ from: `n${index % 300}`, to: `n${(index * 7) % 300}` });
  }
  const start = performance.now();
  for (let frame = 0; frame < 60; frame += 1) {
    cullScene(scene, { x: frame * 50, y: 0, width: 1200, height: 800 });
  }
  // 60 frames of culling take a few milliseconds: far below one frame each.
  assert.ok(performance.now() - start < 200);
});
