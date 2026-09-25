// @ts-check
// The driver editor (SPEC § 6.4): in the inspector, or full-panel in a dialog.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { openModal } from "../../components/modal.js";
import { placement, tabsFor, withDefaults } from "../../lib/driver_config.js";
import { driverChecklist } from "./checklist.js";
import { designSpaceTab, levelsTab } from "./inputs_tabs.js";
import { interfaceTab } from "./interface_tab.js";
import { constraintsTab, objectivesTab, observablesTab, responsesTab } from "./outputs_tabs.js";
import { algorithmTab, executionTab, formulationTab, mdaTab } from "./settings_tabs.js";

/** @type {Record<string, (context: import("./common.js").TabContext) => import("./common.js").TabView>} */
const TAB_VIEWS = {
  design_space: designSpaceTab,
  levels: levelsTab,
  objectives: objectivesTab,
  constraints: constraintsTab,
  observables: observablesTab,
  responses: responsesTab,
  algorithm: algorithmTab,
  formulation: formulationTab,
  mda_settings: mdaTab,
  interface: interfaceTab,
  execution: executionTab,
};

/**
 * Where a driver of the store runs: in the model, nested or under BiLevel.
 *
 * @param {any} driver
 */
function placementOf(driver) {
  const parent = driver.parent ? app.store.node(driver.parent) : null;
  return placement(driver, parent, app.store.rootId);
}

/** The tab shown last for each driver, so that it stays open across selections. */
const lastTab = new Map();

/**
 * Show a tab the next time the editor of a driver opens.
 *
 * @param {string} driverId
 * @param {string} tab
 */
export function requestTab(driverId, tab) {
  lastTab.set(driverId, tab);
}

export class DriverEditor {
  /**
   * @param {any} driver - The driver node of the store.
   * @param {{full?: boolean}} [options]
   */
  constructor(driver, { full = false } = {}) {
    this.driver = driver;
    this.tabs = tabsFor(driver.kind, placementOf(driver));
    this.tab = this.tabs.some((tab) => tab.id === lastTab.get(driver.id)) ? lastTab.get(driver.id) : this.tabs[0]?.id;
    this.configText = JSON.stringify(driver.config ?? {});
    /** @type {Promise<import("./common.js").DriverVariables> | null} */
    this.variablesPromise = null;
    /** @type {import("./common.js").TabView | null} */
    this.view = null;
    this.tabBar = el("div.driver-tabs");
    this.page = el("div.driver-page");
    this.checklist = el("div");
    this.root = el(`div.driver-editor${full ? ".driver-editor-full" : ""}`, {}, [this.checklist, this.tabBar, this.page]);
    if (!full) {
      this.tabBar.append(
        el("button.table-button.driver-expand", {
          text: "⤢",
          title: "Open in a larger window",
          onClick: () => openDriverEditor(this.driver.id, this.tab),
        }),
      );
    }
    this.renderTabs();
    this.renderPage();
    this.renderChecklist();
  }

  /** The steps to set the driver up; kept open or closed as the user left it. */
  renderChecklist() {
    const previous = /** @type {HTMLDetailsElement | null} */ (this.checklist.firstElementChild);
    const next = /** @type {HTMLDetailsElement} */ (driverChecklist(this.driver, (tab) => this.show(tab)));
    // Opened while steps are missing: it stays as the user left it until that changes.
    const ready = String(!next.open);
    if (previous && previous.dataset.ready === ready) {
      next.open = previous.open;
    }
    next.dataset.ready = ready;
    this.checklist.replaceChildren(next);
  }

  /** @returns {import("./common.js").TabContext} */
  context() {
    return {
      driver: this.driver,
      config: withDefaults(this.driver.config),
      placement: placementOf(this.driver),
      variables: () => {
        this.variablesPromise ??= app.api.call("driver.variables", { id: this.driver.id });
        return this.variablesPromise;
      },
    };
  }

  renderTabs() {
    const expand = this.tabBar.querySelector(".driver-expand");
    this.tabBar.replaceChildren(
      ...this.tabs.map((tab) =>
        el(`button.driver-tab-button${tab.id === this.tab ? ".active" : ""}`, {
          text: tab.label,
          onClick: () => this.show(tab.id),
        }),
      ),
    );
    if (expand) {
      this.tabBar.append(expand);
    }
  }

  /** @param {string} tab */
  show(tab) {
    this.tab = tab;
    lastTab.set(this.driver.id, tab);
    this.renderTabs();
    this.renderPage();
  }

  renderPage() {
    const create = TAB_VIEWS[this.tab];
    this.view = create ? create(this.context()) : null;
    this.page.replaceChildren(this.view?.element ?? el("p.placeholder", { text: "Nothing to configure." }));
  }

  /**
   * Refresh after a document change.
   *
   * @param {any} driver
   */
  update(driver) {
    this.driver = driver;
    this.variablesPromise = null; // The variables of the scope may have changed.
    this.renderChecklist();
    // Moving the driver, or changing its parent's formulation, changes its tabs.
    const tabs = tabsFor(driver.kind, placementOf(driver));
    if (tabs.map((tab) => tab.id).join() !== this.tabs.map((tab) => tab.id).join()) {
      this.tabs = tabs;
      if (!tabs.some((tab) => tab.id === this.tab)) {
        this.tab = tabs[0]?.id;
      }
      this.renderTabs();
      this.renderPage();
    }
    const text = JSON.stringify(driver.config ?? {});
    if (text === this.configText) {
      return;
    }
    this.configText = text;
    if (this.view?.update) {
      this.view.update(this.context());
    } else {
      this.renderPage();
    }
  }
}

/**
 * Open the editor of a driver full-panel, in a dialog.
 *
 * @param {string} driverId
 * @param {string} [tab]
 */
export function openDriverEditor(driverId, tab) {
  const driver = app.store.node(driverId);
  if (driver?.type !== "driver") {
    return;
  }
  if (tab) {
    requestTab(driverId, tab);
  }
  const editor = new DriverEditor(driver, { full: true });
  const unsubscribe = app.store.subscribe(() => {
    const current = app.store.node(driverId);
    if (!editor.root.isConnected || !current) {
      unsubscribe();
      if (!current) {
        close();
      }
      return;
    }
    editor.update(current);
  });
  const close = openModal({ title: `${driver.name} — ${driver.kind} driver`, body: editor.root });
}
