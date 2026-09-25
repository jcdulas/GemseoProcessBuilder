// @ts-check
// The views opened by a run: its console tab and its live chart tab.
import { app } from "../app.js";
import { ConsolePanel } from "../panels/console.js";
import { LiveChart } from "../views/run_live/live_chart.js";

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
    const livePage = app.tabs.center.open({ id: `live-${info.id}`, title: `Run: ${info.driver_name}` });
    new LiveChart(livePage, app.runStates, info.id);
  });
  app.runStates.onLog((runId, line) => consoles.get(runId)?.add(line));
}
