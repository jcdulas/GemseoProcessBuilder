// @ts-check
// The status bar: project file, validation, worker and run status (the saved
// state of the project is in the top bar).
import { el } from "../components/dom.js";

const ITEMS = ["project", "validation", "worker", "run"];

export class StatusBar {
  /** @param {HTMLElement} root */
  constructor(root) {
    /** @type {Record<string, HTMLElement>} */
    this.items = {};
    for (const name of ITEMS) {
      const item = el("span.statusbar-item", { dataset: { item: name } });
      if (name === "project") {
        item.classList.add("grow");
      }
      this.items[name] = item;
      root.append(item);
    }
    this.set("project", "No project");
    this.set("worker", "Worker: not started");
  }

  /**
   * @param {string} name - One of project, validation, worker, run.
   * @param {string | Node} content
   * @param {string} [title] - Tooltip.
   */
  set(name, content, title = "") {
    const item = this.items[name];
    item.replaceChildren(content);
    item.title = title;
  }
}
