// @ts-check
// Auto-layout of a level (Ctrl+L): ELK's layered algorithm, left to right,
// computed in a Web Worker; the result is one undoable ``moveNodes``.
import { app } from "../../app.js";
import { showError } from "../../components/errors.js";
import { positionsFromElk, toElkGraph } from "../../lib/elk_graph.js";
import { buildScene } from "../../lib/scene.js";
import { moveScene } from "./render.js";

const WORKER_SCRIPT = "js/workers/elk_worker.js";
const ANIMATION_MS = 250;

/** @type {any} - The ELK API, backed by the worker. */
let elkInWorker = null;
/** Whether workers cannot be used: ELK then runs on the page. */
let noWorker = false;
/** @type {Promise<never> | null} - Rejected when the worker fails. */
let workerFailure = null;

/** A worker running ELK's bundle, started from a Blob (see elk_worker.js). */
function startWorker() {
  const base = new URL(".", document.baseURI).href;
  const source = `self.GPB_BASE = ${JSON.stringify(base)};
importScripts(self.GPB_BASE + ${JSON.stringify(WORKER_SCRIPT)});`;
  const worker = new Worker(URL.createObjectURL(new Blob([source], { type: "text/javascript" })));
  workerFailure = new Promise((_, reject) => {
    worker.addEventListener("error", (event) => {
      event.preventDefault();
      reject(new Error(event.message || "The ELK worker failed."));
    });
  });
  workerFailure.catch(() => {}); // Observed by each layout.
  return worker;
}

/**
 * Lay out an ELK graph, in the worker when possible.
 *
 * @param {any} graph
 * @returns {Promise<any>}
 */
export async function runElk(graph) {
  const ELK = /** @type {any} */ (window).ELK;
  if (!noWorker) {
    try {
      elkInWorker ??= new ELK({ workerFactory: startWorker });
      return await Promise.race([elkInWorker.layout(graph), workerFailure]);
    } catch (error) {
      if (!/** @type {Error} */ (error).message.includes("worker")) {
        throw error; // A layout error, not a worker failure.
      }
      console.warn("ELK runs on the page: the worker failed.", error);
      noWorker = true;
      elkInWorker?.terminateWorker?.();
      elkInWorker = null;
    }
  }
  return new ELK().layout(graph);
}

/**
 * Move nodes smoothly to their new positions, then store them (one undo step).
 *
 * @param {import("./canvas.js").WorkflowCanvas} canvas
 * @param {Record<string, {x: number, y: number}>} positions
 */
function animateTo(canvas, positions) {
  const start = new Map(
    canvas.scene.items.filter((item) => item.id in positions).map((item) => [item.id, { ...item.local }]),
  );
  const began = performance.now();
  return new Promise((resolve) => {
    const frame = () => {
      const t = Math.min(1, (performance.now() - began) / ANIMATION_MS);
      const ease = t * (2 - t);
      canvas.dragPositions.clear();
      for (const [id, from] of start) {
        const to = positions[id];
        canvas.dragPositions.set(id, { x: from.x + (to.x - from.x) * ease, y: from.y + (to.y - from.y) * ease });
      }
      moveScene(canvas.layers, buildScene(app.store.state, canvas.level, canvas.dragPositions, canvas.views));
      if (t < 1) {
        requestAnimationFrame(frame);
      } else {
        resolve(undefined);
      }
    };
    requestAnimationFrame(frame);
  });
}

/**
 * Lay out the selected nodes of the level, or all of them.
 *
 * @param {import("./canvas.js").WorkflowCanvas} canvas
 */
export async function autoLayout(canvas) {
  const level = canvas.scene.items.filter((item) => item.depth === 0);
  const selected = level.filter((item) => canvas.selection.has(item.id));
  const items = selected.length >= 2 ? selected : level;
  if (items.length < 2) {
    return;
  }
  canvas.setHint("Laying out…");
  try {
    const result = await runElk(toElkGraph(items, canvas.scene.links));
    const positions = positionsFromElk(result, items);
    await animateTo(canvas, positions);
    await app.store.execute({ type: "moveNodes", positions });
    if (items === level) {
      // Fit once the moved nodes are drawn (the canvas redraws at the next frame).
      requestAnimationFrame(() => requestAnimationFrame(() => canvas.fit()));
    }
  } catch (error) {
    canvas.dragPositions.clear();
    canvas.render();
    showError("The layout could not be computed", error);
  } finally {
    canvas.setHint("");
  }
}
