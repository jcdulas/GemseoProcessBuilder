// @ts-check
// The driver editor (SPEC § 6.4): in the inspector, or full-panel in a dialog.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { openModal } from "../../components/modal.js";
import { tabsFor, withDefaults } from "../../lib/driver_config.js";
import { designSpaceTab, levelsTab } from "./inputs_tabs.js";
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
  execution: executionTab,
};

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
    this.tabs = tabsFor(driver.kind);
    this.tab = this.tabs.some((tab) => tab.id === lastTab.get(driver.id)) ? lastTab.get(driver.id) : this.tabs[0]?.id;
    this.configText = JSON.stringify(driver.config ?? {});
    /** @type {Promise<import("./common.js").DriverVariables> | null} */
    this.variablesPromise = null;
    /** @type {import("./common.js").TabView | null} */
    this.view = null;
    this.tabBar = el("div.driver-tabs");
    this.page = el("div.driver-page");
    this.root = el(`div.driver-editor${full ? ".driver-editor-full" : ""}`, {}, [this.tabBar, this.page]);
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
  }

  /** @returns {import("./common.js").TabContext} */
  context() {
    return {
      driver: this.driver,
      config: withDefaults(this.driver.config),
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
