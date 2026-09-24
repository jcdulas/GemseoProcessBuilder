// @ts-check
// The Library panel: built-in node types and the components of catalog folders.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { openModal } from "../components/modal.js";
import { BUILTIN_ITEMS, nodeFromEntry, searchItems } from "../lib/builtins.js";

/** Drag and drop type carrying the node to create. */
export const NEW_NODE_TYPE = "application/x-gpb-new-node";

/**
 * Make an element draggable as a new node.
 *
 * @param {HTMLElement} element
 * @param {object} node
 */
function makeDraggable(element, node) {
  element.draggable = true;
  element.addEventListener("dragstart", (event) => {
    event.dataTransfer?.setData(NEW_NODE_TYPE, JSON.stringify(node));
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "copy";
    }
  });
  element.addEventListener("dblclick", () => app.canvas.addNodeAtCenter(node));
}

/** @param {{path: string, message: string, traceback: string}} error */
function showScanError(error) {
  openModal({
    title: `Cannot import ${error.path.split(/[\\/]/).pop()}`,
    body: el("div", {}, [el("p", { text: error.message }), el("pre.console-lines", { text: error.traceback })]),
  });
}

export class LibraryPanel {
  /** @param {HTMLElement} root */
  constructor(root) {
    root.replaceChildren();
    root.classList.add("library-page");
    this.search = /** @type {HTMLInputElement} */ (
      el("input.input.library-search", { type: "search", placeholder: "Search components…" })
    );
    this.search.addEventListener("input", () => this.render());
    this.status = el("div.library-status");
    this.list = el("div.library-list");
    root.append(
      el("div.library-toolbar", {}, [
        this.search,
        el("button.button", { text: "Refresh", title: "Scan the catalog folders again", onClick: () => app.api.call("catalog.refresh") }),
      ]),
      this.status,
      this.list,
    );
    /** @type {any} */
    this.catalog = { scanning: false, folders: [], errors: [] };
    /** @type {Set<string>} */
    this.collapsed = new Set();
    app.api.on("catalog.updated", (catalog) => {
      this.catalog = catalog;
      this.render();
    });
    app.api.call("catalog.list").then((catalog) => {
      this.catalog = catalog;
      this.render();
    });
  }

  /**
   * @param {string} key
   * @param {string} title
   * @param {HTMLElement[]} rows
   * @param {HTMLElement | null} [extra]
   */
  section(key, title, rows, extra = null) {
    const collapsed = this.collapsed.has(key) && !this.search.value;
    const header = el("div.library-section-header", {
      onClick: () => {
        if (this.collapsed.has(key)) {
          this.collapsed.delete(key);
        } else {
          this.collapsed.add(key);
        }
        this.render();
      },
    }, [el("span.tree-expander", { text: collapsed ? "▸" : "▾" }), el("span", { text: title }), extra]);
    return el("div.library-section", {}, [header, ...(collapsed ? [] : rows)]);
  }

  /**
   * @param {string} label
   * @param {string} description
   * @param {string} iconClass
   * @param {object} node
   * @param {number} [depth]
   */
  item(label, description, iconClass, node, depth = 1) {
    const element = el("div.library-item", { title: description }, [
      el(`span.tree-icon.${iconClass}`),
      el("span.tree-label", { text: label }),
    ]);
    element.style.paddingLeft = `${8 + depth * 12}px`;
    makeDraggable(element, node);
    return element;
  }

  render() {
    const text = this.search.value;
    const sections = [];
    const groups = [...new Set(BUILTIN_ITEMS.map((item) => item.group))];
    for (const group of groups) {
      const items = searchItems(BUILTIN_ITEMS.filter((item) => item.group === group), text);
      if (items.length) {
        sections.push(
          this.section(
            `builtin:${group}`,
            group,
            items.map((item) => {
              const node = /** @type {any} */ (item.node);
              const icon = node.type === "driver" ? `tree-icon-driver-${node.kind}` : `tree-icon-${node.type}`;
              return this.item(item.label, item.description, icon, item.node);
            }),
          ),
        );
      }
    }

    for (const folder of this.catalog.folders) {
      const rows = [];
      for (const file of folder.files) {
        const entries = searchItems(
          file.entries.map((/** @type {any} */ entry) => ({ ...entry, label: entry.name })),
          text,
        );
        if (file.error && !text) {
          const row = el("div.library-item.library-error", {
            title: "Click to see the error",
            onClick: () => showScanError(file.error),
          }, [el("span.library-warning", { text: "⚠" }), el("span.tree-label", { text: file.relative })]);
          row.style.paddingLeft = "20px";
          rows.push(row);
        } else if (entries.length) {
          const label = el("div.library-file", { text: file.relative });
          rows.push(label);
          for (const entry of entries) {
            rows.push(this.item(entry.name, entry.description || entry.module_path, "tree-icon-component", nodeFromEntry(entry), 2));
          }
        }
      }
      const name = folder.path.split(/[\\/]/).filter(Boolean).pop() ?? folder.path;
      const note = folder.exists ? (rows.length ? null : el("div.library-empty", { text: "No components found." })) : el("div.library-empty", { text: "This folder does not exist." });
      sections.push(
        this.section(`folder:${folder.path}`, name, note ? [...rows, note] : rows, el("span.library-path", { text: folder.path })),
      );
    }
    this.list.replaceChildren(...sections);

    const statusText = this.catalog.scanning
      ? "Scanning the catalog folders…"
      : this.catalog.errors?.length
        ? `The catalog could not be scanned: ${this.catalog.errors[0]}`
        : this.catalog.folders.length
          ? ""
          : "Add catalog folders in Tools › Preferences or Model › Project settings.";
    this.status.textContent = statusText;
    this.status.hidden = !statusText;
  }
}
