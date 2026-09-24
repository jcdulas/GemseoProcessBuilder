// @ts-check
// Tab groups: the static tabs of index.html plus tabs opened by the views.
import { el } from "../components/dom.js";

export class TabGroup {
  /** @param {HTMLElement} root - An element with the `tab-group` class. */
  constructor(root) {
    this.root = root;
    this.bar = /** @type {HTMLElement} */ (root.querySelector(".tab-bar"));
    this.pages = /** @type {HTMLElement} */ (root.querySelector(".tab-pages"));
    /** @type {Set<(id: string) => void>} */
    this.listeners = new Set();
    this.bar.addEventListener("click", (event) => {
      const tab = /** @type {HTMLElement} */ (event.target).closest(".tab");
      if (tab instanceof HTMLElement && tab.dataset.tab) {
        this.activate(tab.dataset.tab);
      }
    });
    const first = this.bar.querySelector(".tab");
    if (first instanceof HTMLElement && first.dataset.tab) {
      this.activate(first.dataset.tab);
    }
  }

  /** @returns {string | undefined} */
  get active() {
    return /** @type {HTMLElement | null} */ (this.bar.querySelector(".tab.active"))?.dataset.tab;
  }

  /** @param {string} id */
  activate(id) {
    for (const tab of this.bar.querySelectorAll(".tab")) {
      tab.classList.toggle("active", /** @type {HTMLElement} */ (tab).dataset.tab === id);
    }
    for (const page of this.pages.querySelectorAll(":scope > .tab-page")) {
      page.classList.toggle("active", /** @type {HTMLElement} */ (page).dataset.page === id);
    }
    for (const listener of this.listeners) {
      listener(id);
    }
  }

  /**
   * @param {string} id
   * @returns {HTMLElement | null}
   */
  page(id) {
    return this.pages.querySelector(`:scope > .tab-page[data-page="${id}"]`);
  }

  /**
   * Open a tab, or activate it if it already exists.
   *
   * @param {{id: string, title: string, closable?: boolean, onClose?: () => void}} options
   * @returns {HTMLElement} The page element of the tab.
   */
  open({ id, title, closable = true, onClose }) {
    let page = this.page(id);
    if (!page) {
      const tab = el("div.tab", { dataset: { tab: id }, role: "tab" }, [el("span", { text: title })]);
      if (closable) {
        tab.append(
          el("button.tab-close", {
            title: "Close",
            text: "×",
            onClick: (/** @type {Event} */ event) => {
              event.stopPropagation();
              this.close(id);
              onClose?.();
            },
          }),
        );
      }
      this.bar.append(tab);
      page = el("section.tab-page", { dataset: { page: id } });
      this.pages.append(page);
    }
    this.activate(id);
    return page;
  }

  /** @param {string} id */
  close(id) {
    const wasActive = this.active === id;
    this.bar.querySelector(`.tab[data-tab="${id}"]`)?.remove();
    this.page(id)?.remove();
    const first = this.bar.querySelector(".tab");
    if (wasActive && first instanceof HTMLElement && first.dataset.tab) {
      this.activate(first.dataset.tab);
    }
  }

  /**
   * Show a count next to a tab title (hidden when zero).
   *
   * @param {string} id
   * @param {number} count
   */
  setBadge(id, count) {
    const tab = this.bar.querySelector(`.tab[data-tab="${id}"]`);
    if (!tab) {
      return;
    }
    let badge = tab.querySelector(".tab-badge");
    if (!count) {
      badge?.remove();
      return;
    }
    if (!badge) {
      badge = el("span.tab-badge");
      tab.append(badge);
    }
    badge.textContent = String(count);
  }

  /** @param {(id: string) => void} listener */
  onChange(listener) {
    this.listeners.add(listener);
  }
}
