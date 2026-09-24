// @ts-check
// Worker status in the status bar, and Tools › Restart worker.
import { app } from "../app.js";
import { el } from "../components/dom.js";

const STATE_LABELS = {
  stopped: "stopped",
  starting: "starting…",
  ready: "ready",
  busy: "busy",
  crashed: "stopped after errors",
  incompatible: "incompatible environment",
};

/** @param {{state: string, detail: string, versions: Record<string, string>}} status */
function showStatus(status) {
  const label = STATE_LABELS[/** @type {keyof STATE_LABELS} */ (status.state)] ?? status.state;
  const text = `Worker: ${label}${status.detail && status.state !== "crashed" ? ` — ${status.detail}` : ""}`;
  app.statusBar.set(
    "worker",
    el(`span.worker-state.worker-${status.state}`, { text }),
    status.detail || text,
  );
  app.workerStatus = status;
}

export async function installWorkerStatus() {
  app.api.on("worker.status", showStatus);
  showStatus(await app.api.call("worker.status"));
  app.actions.handle("tools.restartWorker", {
    run: () => app.api.call("worker.restart"),
  });
}
