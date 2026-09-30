// @ts-check
// Run › Run (F5) and Run › Stop (Shift+F5), and the run status in the status bar.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";
import { showToast } from "../components/toast.js";
import { openResults } from "../views/results/results_tab.js";
import { enclosingDriver } from "../lib/driver_config.js";

/** @type {Map<string, any>} */
const runs = new Map();

const STATUS_LABELS = {
  preparing: "checking the script…",
  running: "running…",
  completed: "completed",
  stopped: "stopped",
  failed: "failed",
  killed: "killed",
};

/**
 * What F5 runs: the selected driver (or the driver around the selection),
 * else the driver shown on the canvas, else the first top-level driver.
 *
 * @returns {string | null}
 */
export function runTarget() {
  const ids = app.selection.list();
  const candidates = ids.length === 1 ? [ids[0]] : [];
  candidates.push(app.navigation.current());
  for (const id of candidates) {
    const node = app.store.node(id);
    if (node?.type === "driver") {
      return id;
    }
    const driver = enclosingDriver([...app.store.pathTo(id), id], (nodeId) => app.store.node(nodeId));
    if (driver) {
      return driver.id;
    }
  }
  return null; // Python picks the first top-level driver, or the model.
}

/**
 * "1:05" from milliseconds.
 *
 * @param {number} milliseconds
 */
export function formatElapsed(milliseconds) {
  const seconds = Math.floor(milliseconds / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const rest = `${String(minutes % 60).padStart(hours ? 2 : 1, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  return hours ? `${hours}:${rest}` : rest;
}

/** The progress of the current run: bar, count, elapsed time and Stop. */
function progressItem() {
  const record = app.runStates.current();
  if (!record) {
    return null;
  }
  const progress = record.data.progress;
  const elapsed = formatElapsed((record.finishedAt ?? performance.now()) - record.startedAt);
  const parts = [];
  if (progress?.total) {
    const bar = /** @type {HTMLProgressElement} */ (el("progress.run-progress", { max: progress.total }));
    // An optimization often converges before its maximum number of iterations.
    bar.value = record.info.status === "completed" ? progress.total : progress.current;
    parts.push(bar, el("span", { text: `${progress.current}/${progress.total} ${progress.unit}s` }));
  } else if (progress) {
    parts.push(el("span", { text: `${progress.current} ${progress.unit}s` }));
  }
  // A nested scenario runs many times: its own iterations, as a secondary indicator.
  const inner = record.data.inner.get(record.data.lastInner);
  if (inner && app.runStates.isActive(record)) {
    parts.push(el("span.run-inner", { text: `${inner.name}: iteration ${inner.current}` }));
  }
  if (progress?.processes > 1) {
    parts.push(
      el("span.run-inner", {
        text: `${progress.processes} processes`,
        title: "The samples run in child processes: the state of each component is not shown.",
      }),
    );
  }
  parts.push(el("span.run-elapsed", { text: elapsed }));
  if (app.runStates.isActive(record)) {
    parts.push(el("button.table-button", { text: "Stop", title: "Stop the run (Shift+F5)", onClick: () => app.actions.invoke("run.stop") }));
  }
  return el("span.run-progress-item", {}, parts);
}

function refresh() {
  const active = [...runs.values()].filter((run) => run.status === "preparing" || run.status === "running");
  app.actions.setEnabled("run.stop", active.length > 0);
  app.actions.setEnabled("run.start", active.length === 0);
  const latest = [...runs.values()].at(-1);
  if (!latest) {
    app.statusBar.set("run", "");
    return;
  }
  const label = STATUS_LABELS[/** @type {keyof STATUS_LABELS} */ (latest.status)] ?? latest.status;
  app.statusBar.set(
    "run",
    el("span.run-status", {}, [
      el(`span.run-state.run-${latest.status}`, { text: `${latest.driver_name}: ${label}` }),
      progressItem(),
    ]),
    latest.error ?? latest.id,
  );
}

/** @param {any} run */
function update(run) {
  runs.set(run.id, run);
  refresh();
}

/**
 * Tell the user how a run ended.
 *
 * @param {any} run
 */
function announce(run) {
  const results = { label: "View results", run: () => openResults(run.id) };
  if (run.status === "completed") {
    showToast({ title: `${run.driver_name} completed`, message: "The results are ready.", action: results });
  } else if (run.status === "failed") {
    showToast({
      title: `${run.driver_name} failed`,
      message: "See the console of the run for the details.",
      level: "error",
      action: run.error ? { label: "Details", run: () => showError(`${run.driver_name} failed`, run.error) } : undefined,
    });
  } else {
    showToast({ title: `${run.driver_name} ${STATUS_LABELS[/** @type {keyof STATUS_LABELS} */ (run.status)] ?? run.status}`, level: "info", action: results });
  }
}

export async function installRunActions() {
  const { actions, api } = app;
  actions.handle("run.start", {
    run: async () => {
      try {
        update(await api.call("run.start", { target: runTarget() }));
      } catch (error) {
        showError("The run cannot start", error);
      }
    },
  });
  actions.handle("run.stop", { run: () => api.call("run.stop", {}).catch((error) => showError("The run cannot be stopped", error)) });
  api.on("run.started", update);
  api.on("run.updated", update);
  api.on("run.finished", (/** @type {any} */ run) => {
    update(run);
    announce(run);
  });
  app.runStates.onChange(refresh);
  // The elapsed time moves on while a run is active.
  setInterval(() => {
    const record = app.runStates.current();
    if (record && app.runStates.isActive(record)) {
      refresh();
    }
  }, 1000);
  const state = await api.call("run.state");
  for (const run of state.runs) {
    runs.set(run.id, run);
  }
  refresh();
}
