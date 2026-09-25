// @ts-check
// Run › Run (F5) and Run › Stop (Shift+F5), and the run status in the status bar.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";
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
    el(`span.run-state.run-${latest.status}`, { text: `${latest.driver_name}: ${label}` }),
    latest.error ?? latest.id,
  );
}

/** @param {any} run */
function update(run) {
  runs.set(run.id, run);
  refresh();
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
    if (run.status === "failed" && run.error) {
      showError(`${run.driver_name} failed`, run.error);
    }
  });
  const state = await api.call("run.state");
  for (const run of state.runs) {
    runs.set(run.id, run);
  }
  refresh();
}
