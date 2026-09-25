// @ts-check
// Scripted benchmark scenarios (SPEC § 14.1, § 15.5), run by the benchmark mode
// of the application: `benchmarks/run.py` starts it on a synthetic model, the
// page runs the scenarios and reports the measurements to Python.
//
// Frame rates are measured with requestAnimationFrame: the window must be
// visible, otherwise the browser slows the frames down.
import { app } from "../app.js";
import { openN2, currentN2 } from "../views/n2/n2_view.js";
import { autoLayout } from "../views/canvas/auto_layout.js";
import { openResults } from "../views/results/results_tab.js";

/** The level of the synthetic model with 300 components. */
const BIG_LEVEL = "n-big";
const FRAMES = 120;

const frame = () => new Promise((resolve) => requestAnimationFrame(resolve));
const pause = (/** @type {number} */ ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Statistics of durations, in milliseconds.
 *
 * @param {number[]} values
 */
export function stats(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const at = (/** @type {number} */ q) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
  const round = (/** @type {number} */ value) => Math.round(value * 10) / 10;
  return { count: values.length, median_ms: round(at(0.5)), p95_ms: round(at(0.95)), max_ms: round(sorted[sorted.length - 1]) };
}

/**
 * Run a step at each frame; the frame rate and the longest frame.
 *
 * @param {(index: number) => void} step
 */
async function frameRate(step) {
  const times = [];
  for (let index = 0; index < FRAMES; index += 1) {
    step(index);
    times.push(await frame());
  }
  const gaps = times.slice(1).map((time, index) => time - times[index]);
  const seconds = (times[times.length - 1] - times[0]) / 1000;
  return { fps: Math.round(((times.length - 1) / seconds) * 10) / 10, ...stats(gaps) };
}

/**
 * Wait until a condition holds, checking at each frame.
 *
 * @param {() => boolean} condition
 * @param {number} [timeoutMs]
 */
async function until(condition, timeoutMs = 60_000) {
  const start = performance.now();
  while (!condition()) {
    if (performance.now() - start > timeoutMs) {
      throw new Error("The benchmark waited too long.");
    }
    await frame();
  }
}

/** @param {string} path */
async function measureOpen(path) {
  const start = performance.now();
  let reset = false;
  const stop = app.store.subscribe((event) => {
    reset ||= event.type === "reset";
  });
  const opened = await app.api.call("project.open", { path }, { timeout: 300_000 });
  const answered = performance.now() - start;
  await until(() => reset);
  stop();
  await frame();
  await frame();
  return { answered_ms: Math.round(answered), total_ms: Math.round(performance.now() - start), cancelled: Boolean(opened?.cancelled) };
}

async function measureCommands() {
  app.navigation.enter(BIG_LEVEL);
  // The couplings of the level are loaded first.
  await pause(2000);
  const durations = [];
  for (let index = 0; index < 20; index += 1) {
    const start = performance.now();
    await app.store.execute({ type: "setNodeProperties", id: "n-c0", values: { description: `Benchmark ${index}` } });
    await frame();
    durations.push(performance.now() - start);
  }
  return { ...stats(durations), in_order_ms: durations.map(Math.round) };
}

async function measureValidation() {
  const durations = [];
  let problems = 0;
  for (let index = 0; index < 3; index += 1) {
    const start = performance.now();
    const counts = await app.api.call("validation.run", undefined, { timeout: 120_000 });
    durations.push(performance.now() - start);
    problems = counts.error + counts.warning + counts.info;
  }
  return { ...stats(durations), problems };
}

async function measureCanvas() {
  app.navigation.enter(BIG_LEVEL);
  await pause(1000);
  const canvas = app.canvas;
  const d3 = /** @type {any} */ (window).d3;
  // Zoom out and in around the level, then pan across it.
  const zoom = await frameRate((index) => {
    const k = 0.25 + 0.75 * Math.abs(Math.sin((index / FRAMES) * Math.PI * 2));
    canvas.svg.call(canvas.zoom.transform, d3.zoomIdentity.translate(40, 40).scale(k));
  });
  const pan = await frameRate((index) => {
    canvas.svg.call(canvas.zoom.transform, d3.zoomIdentity.translate(-index * 40, -index * 20).scale(1));
  });
  const nodes = canvas.container.querySelectorAll("g.node").length;
  return { zoom, pan, nodes_in_dom: nodes };
}

async function measureN2() {
  const start = performance.now();
  openN2({ level: app.store.rootId });
  const view = /** @type {any} */ (currentN2());
  await until(() => view.view.entries.length > 0);
  await frame();
  const built = performance.now() - start;
  const d3 = /** @type {any} */ (window).d3;
  const entries = view.view.entries.length;
  const scroll = await frameRate((index) => {
    view.svg.call(view.zoom.transform, d3.zoomIdentity.translate(0, -index * 120).scale(1));
  });
  return { entries, open_ms: Math.round(built), scroll };
}

async function measureLayout() {
  app.navigation.enter(BIG_LEVEL);
  await pause(1000);
  // Frames keep being drawn while the layout runs in its worker.
  let running = true;
  const gaps = [];
  const watch = (async () => {
    let last = await frame();
    while (running) {
      const now = await frame();
      gaps.push(now - last);
      last = now;
    }
  })();
  const start = performance.now();
  await autoLayout(app.canvas);
  const duration = performance.now() - start;
  running = false;
  await watch;
  return { duration_ms: Math.round(duration), frames_during_layout: stats(gaps) };
}

async function measureResults() {
  const timings = {};
  for (const view of ["table", "scatter", "parallel", "xy"]) {
    const start = performance.now();
    openResults("r-benchmark", { view });
    const page = /** @type {HTMLElement} */ (app.tabs.center.page("results-r-benchmark"));
    try {
      await until(() => {
        const shown = page.querySelector(".results-page:not([hidden])");
        return Boolean(shown?.querySelector(".data-body .data-cell, svg circle, svg path, svg rect"));
      }, 30_000);
      await frame();
      timings[view] = Math.round(performance.now() - start);
    } catch {
      timings[view] = "not drawn within 30 s";
    }
  }
  return timings;
}

const SCENARIOS = {
  command: measureCommands,
  validation: measureValidation,
  canvas: measureCanvas,
  n2: measureN2,
  layout: measureLayout,
  results: measureResults,
};

/**
 * Run a scenario (or all) on a project and report the measurements.
 *
 * @param {{name: string, project: string}} scenario
 */
export async function runBenchmark({ name, project }) {
  /** @type {Record<string, any>} */
  const results = { scenario: name, userAgent: navigator.userAgent };
  try {
    results.open = await measureOpen(project);
    for (const [key, measure] of Object.entries(SCENARIOS)) {
      if (name === "all" || name === key) {
        console.info(`Benchmark: ${key}…`);
        results[key] = await measure();
      }
    }
  } catch (error) {
    results.error = String(error);
  }
  await app.api.call("benchmark.report", { results });
}
