// @ts-check
// Entry point of the page: connects to Python and builds the application frame.
import { app } from "./app.js";
import { connect } from "./bridge.js";
import { ConsolePanel } from "./panels/console.js";
import { ActionRegistry } from "./shell/actions.js";
import { showAbout, showShortcuts } from "./shell/help.js";
import { PanelLayout } from "./shell/layout.js";
import { installShortcuts } from "./shell/shortcuts.js";
import { StatusBar } from "./shell/statusbar.js";
import { TabGroup } from "./shell/tabs.js";
import { buildToolbar } from "./shell/toolbar.js";

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

buildToolbar(/** @type {HTMLElement} */ (document.getElementById("toolbar")), actions);
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

console.info(`Page ready: application ${version}, d3 ${/** @type {any} */ (window).d3.version}`);
