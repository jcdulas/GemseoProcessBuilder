// @ts-check
// The views opened by a run: its console tab and its Results tab.
import { app } from "../app.js";
import { ConsolePanel } from "../panels/console.js";
import { openResults } from "../views/results/results_tab.js";

export function installRunViews() {
  /** @type {Map<string, ConsolePanel>} */
  const consoles = new Map();
  app.api.on("run.started", (/** @type {any} */ info) => {
    // Closing these tabs does not stop the run.
    const consolePage = app.tabs.bottom.open({
      id: `run-${info.id}`,
      title: `Run ${info.driver_name}`,
      onClose: () => consoles.delete(info.id),
    });
    consoles.set(info.id, new ConsolePanel(consolePage, null));
    openResults(info.id, { view: "history" });
  });
  app.runStates.onLog((runId, line) => consoles.get(runId)?.add(line));
}
