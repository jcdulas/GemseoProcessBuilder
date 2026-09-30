// @ts-check
// The icon rail on the left: it opens and closes the panels of the frame.
import { app } from "../app.js";
import { el, icon } from "../components/dom.js";

/** Tabs whose count is shown on the rail: what needs the attention of the user. */
const BADGES = new Set(["problems"]);

/**
 * Entries of the rail: [icon, label, panel, tab of the panel], or "|" to push
 * the next entries to the bottom.
 */
const ENTRIES = [
  ["nodes", "Nodes", "left", "library"],
  ["tree", "Model tree", "left", "tree"],
  ["problems", "Problems", "bottom", "problems"],
  ["runs", "Runs", "bottom", "runs"],
  ["console", "Console", "bottom", "console"],
  "|",
  ["settings", "Preferences", null, "tools.preferences"],
  ["help", "Keyboard shortcuts", null, "help.shortcuts"],
];

export class Rail {
  /** @param {HTMLElement} root */
  constructor(root) {
    /** @type {{button: HTMLElement, panel: string, tab: string}[]} */
    this.entries = [];
    for (const entry of ENTRIES) {
      if (entry === "|") {
        root.append(el("div.rail-spacer"));
        continue;
      }
      const [iconName, label, panel, target] = entry;
      const button = el("button.rail-button", { title: label, "aria-label": label }, [
        icon(/** @type {any} */ (iconName)),
      ]);
      if (panel) {
        button.addEventListener("click", () => this.toggle(panel, /** @type {string} */ (target)));
        this.entries.push({ button, panel, tab: /** @type {string} */ (target) });
      } else {
        button.addEventListener("click", () => app.actions.invoke(/** @type {string} */ (target)));
      }
      root.append(button);
    }
    app.layout.onChange(() => this.refresh());
    for (const group of [app.tabs.left, app.tabs.bottom]) {
      group.onChange(() => this.refresh());
      group.onBadge((id, count) => this.setBadge(id, count));
    }
    for (const button of document.querySelectorAll("[data-close-panel]")) {
      const panel = /** @type {HTMLElement} */ (button).dataset.closePanel ?? "";
      button.addEventListener("click", () => app.layout.isVisible(panel) && app.layout.toggle(panel));
    }
    this.refresh();
  }

  /**
   * Show a tab of a panel, or hide the panel if that tab is already shown.
   *
   * @param {string} panel
   * @param {string} tab
   */
  toggle(panel, tab) {
    const group = app.tabs[/** @type {"left" | "bottom"} */ (panel)];
    if (app.layout.isVisible(panel) && group.active === tab) {
      app.layout.toggle(panel);
      return;
    }
    group.activate(tab);
    if (!app.layout.isVisible(panel)) {
      app.layout.toggle(panel);
    }
  }

  refresh() {
    for (const { button, panel, tab } of this.entries) {
      const group = app.tabs[/** @type {"left" | "bottom"} */ (panel)];
      button.classList.toggle("active", app.layout.isVisible(panel) && group.active === tab);
    }
  }

  /**
   * @param {string} tab
   * @param {number} count
   */
  setBadge(tab, count) {
    const entry = this.entries.find((candidate) => candidate.tab === tab);
    if (!entry || !BADGES.has(tab)) {
      return;
    }
    entry.button.querySelector(".rail-badge")?.remove();
    if (count) {
      entry.button.append(el("span.rail-badge", { text: count > 99 ? "99+" : String(count) }));
    }
  }
}
