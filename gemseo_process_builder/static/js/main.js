// @ts-check
// Entry point of the page: connects to Python and builds the application frame.
import { app } from "./app.js";
import { connect } from "./bridge.js";
import { ConsolePanel } from "./panels/console.js";
import { InspectorPanel } from "./panels/inspector.js";
import { LibraryPanel } from "./panels/library.js";
import { ProblemsPanel, installValidation } from "./panels/problems.js";
import { RunsPanel } from "./panels/runs.js";
import { installProjectSettings } from "./shell/project_settings.js";
import { TreePanel } from "./panels/tree.js";
import { ActionRegistry } from "./shell/actions.js";
import { installEditActions } from "./shell/edit.js";
import { showAbout, showShortcuts } from "./shell/help.js";
import { PanelLayout } from "./shell/layout.js";
import { showPreferences } from "./shell/preferences_dialog.js";
import { installProjectActions } from "./shell/project.js";
import { installRunActions } from "./shell/run.js";
import { installRunViews } from "./shell/run_views.js";
import { installResults } from "./views/results/results_tab.js";
import { installShortcuts } from "./shell/shortcuts.js";
import { StatusBar } from "./shell/statusbar.js";
import { TabGroup } from "./shell/tabs.js";
import { buildToolbar } from "./shell/toolbar.js";
import { Rail } from "./shell/rail.js";
import { installWorkerStatus } from "./shell/worker.js";
import { ComponentStatus } from "./services/component_status.js";
import { LinkFocus } from "./services/link_focus.js";
import { ValidationState } from "./services/validation.js";
import { DriverRoles } from "./services/driver_roles.js";
import { BrushSelection } from "./services/brush_selection.js";
import { RunStates } from "./services/run_state.js";
import { Navigation } from "./services/navigation.js";
import { Selection } from "./services/selection.js";
import { DocumentStore } from "./store.js";
import { installWorkflow } from "./views/canvas/workflow.js";
import { installN2 } from "./views/n2/n2_view.js";
import { installXdsm } from "./views/xdsm/xdsm_view.js";
import { installImageExport } from "./services/export.js";
import { installReportExport } from "./shell/report_dialog.js";
import { runBenchmark } from "./services/benchmark.js";
import { installWrapperEditor } from "./views/wrapper_editor/editor.js";
import { openContextMenu } from "./components/context_menu.js";
import { isTypingTarget } from "./lib/shortcut_keys.js";

// Uncaught errors reach the log of the application and its Console panel.
window.addEventListener("error", (event) => {
  console.error(`Uncaught error: ${event.message} (${event.filename}:${event.lineno})`, event.error?.stack ?? "");
});
window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  console.error(`Unhandled rejection: ${reason?.message ?? reason}`, reason?.stack ?? "");
});

const api = await connect();
const [preferences, { version }] = await Promise.all([api.call("prefs.get"), api.call("app.version")]);

const actions = new ActionRegistry(api);
await actions.load();

Object.assign(app, {
  api,
  actions,
  version,
  statusBar: new StatusBar(/** @type {HTMLElement} */ (document.getElementById("statusbar"))),
  layout: new PanelLayout(api, preferences.layout?.panels),
  tabs: {
    left: new TabGroup(/** @type {HTMLElement} */ (document.querySelector('[data-tab-group="left"]'))),
    center: new TabGroup(/** @type {HTMLElement} */ (document.querySelector('[data-tab-group="center"]'))),
    bottom: new TabGroup(/** @type {HTMLElement} */ (document.querySelector('[data-tab-group="bottom"]'))),
  },
  console: new ConsolePanel(/** @type {HTMLElement} */ (document.getElementById("console")), api),
});
/** @type {any} */ (window).app = app; // Handy from the DevTools console.

app.projectTitle = buildToolbar(/** @type {HTMLElement} */ (document.getElementById("toolbar")), actions);
new Rail(/** @type {HTMLElement} */ (document.getElementById("rail")));
installShortcuts(actions);

for (const [id, panel] of [
  ["view.toggleLeft", "left"],
  ["view.toggleRight", "right"],
  ["view.toggleBottom", "bottom"],
]) {
  actions.handle(id, { run: () => app.layout.toggle(panel), checked: app.layout.isVisible(panel) });
}
app.layout.onChange(() => {
  actions.setChecked("view.toggleLeft", app.layout.isVisible("left"));
  actions.setChecked("view.toggleRight", app.layout.isVisible("right"));
  actions.setChecked("view.toggleBottom", app.layout.isVisible("bottom"));
});
actions.handle("help.shortcuts", { run: () => showShortcuts(actions) });
actions.handle("help.about", { run: () => showAbout(version) });
await installProjectActions();

app.store = new DocumentStore(api);
await app.store.reload();
app.selection = new Selection();
app.componentStatus = new ComponentStatus(api);
app.linkFocus = new LinkFocus();
app.validation = new ValidationState(api);
app.selection.onChange((ids) => {
  if (ids.size) {
    app.linkFocus.set(null);
  }
});
app.navigation = new Navigation(app.store);
app.driverRoles = new DriverRoles();
app.runStates = new RunStates(api, app.store);
app.brushSelection = new BrushSelection();
await installEditActions();
await installWorkerStatus();
await installRunActions();
installRunViews();
installResults();
actions.handle("tools.preferences", { run: () => showPreferences() });
actions.handle("tools.devTools", { run: () => api.call("app.openDevTools") });
// A right click without a menu of its own offers the developer tools; text
// fields keep their menu (cut, copy, paste).
document.addEventListener("contextmenu", (event) => {
  if (event.defaultPrevented || isTypingTarget(/** @type {any} */ (event.target))) {
    return;
  }
  event.preventDefault();
  openContextMenu(event.clientX, event.clientY, [
    { label: "Open developer tools", shortcut: "F12", run: () => actions.invoke("tools.devTools") },
  ]);
});
installProjectSettings();
installWorkflow();
installN2();
installXdsm();
installWrapperEditor();
installImageExport();
installReportExport();
new LibraryPanel(/** @type {HTMLElement} */ (app.tabs.left.page("library")));
new TreePanel(/** @type {HTMLElement} */ (app.tabs.left.page("tree")));
new ProblemsPanel(/** @type {HTMLElement} */ (app.tabs.bottom.page("problems")));
new RunsPanel(/** @type {HTMLElement} */ (app.tabs.bottom.page("runs")));
installValidation();
new InspectorPanel(/** @type {HTMLElement} */ (document.getElementById("inspector")));

console.info(`Page ready: application ${version}, d3 ${/** @type {any} */ (window).d3.version}`);

// In benchmark mode, the page runs the scenario asked by Python.
const benchmark = await api.call("benchmark.scenario");
if (benchmark) {
  runBenchmark(benchmark);
}
