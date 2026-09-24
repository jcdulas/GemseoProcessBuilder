// @ts-check
// The model tree: assemblies, drivers, components and their variables.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";
import { VirtualList } from "../components/virtual_list.js";
import { ancestorsToReveal, flattenTree } from "../lib/tree_flatten.js";
import { nodeMenu } from "../views/canvas/menus.js";
import { NEW_NODE_TYPE } from "./library.js";

const INDENT = 14;
const DRAG_TYPE = "application/x-gpb-node-ids";

export class TreePanel {
  /** @param {HTMLElement} root */
  constructor(root) {
    root.replaceChildren();
    root.classList.add("tree-page");
    /** @type {Set<string>} */
    this.expanded = new Set(app.store.state.view.tree_expanded ?? []);
    this.list = new VirtualList(root, { renderRow: (row) => this.renderRow(row) });
    /** @type {import("../lib/tree_flatten.js").TreeRow[]} */
    this.rows = [];
    app.store.subscribe((event) => {
      if (event.type === "reset") {
        this.expanded = new Set(app.store.state.view.tree_expanded ?? []);
      }
      this.refresh();
    });
    app.selection.onChange(() => this.revealSelection());
    app.validation.onChange(() => this.list.render());
    this.refresh();
  }

  refresh() {
    this.rows = flattenTree(app.store.state, this.expanded);
    this.list.setRows(this.rows);
  }

  /** Expand the ancestors of the selected nodes and scroll to the first one. */
  revealSelection() {
    const [first] = app.selection.list();
    if (first) {
      for (const id of ancestorsToReveal(app.store.state, first)) {
        this.expanded.add(id);
      }
    }
    this.refresh();
    const index = this.rows.findIndex((row) => row.type === "node" && row.nodeId === first);
    if (index >= 0) {
      this.list.scrollToIndex(index);
    }
  }

  /** @param {string} id */
  toggle(id) {
    if (this.expanded.has(id)) {
      this.expanded.delete(id);
    } else {
      this.expanded.add(id);
    }
    this.refresh();
    app.store
      .execute({ type: "setLayout", tree_expanded: [...this.expanded] }, { undoable: false })
      .catch((error) => console.error(error));
  }

  /**
   * Select a node from the tree: the canvas shows its level.
   *
   * @param {string} id
   * @param {boolean} additive
   */
  select(id, additive) {
    if (id === app.store.rootId) {
      app.navigation.enter(id);
      app.selection.clear();
      return;
    }
    if (additive) {
      app.selection.toggle(id);
      return;
    }
    app.navigation.reveal(id);
    app.selection.set([id]);
  }

  /** @param {import("../lib/tree_flatten.js").TreeRow} row */
  renderRow(row) {
    const selected = row.type === "node" && app.selection.has(row.nodeId);
    const element = el(`div.tree-row${selected ? ".selected" : ""}`);
    element.style.paddingLeft = `${4 + row.depth * INDENT}px`;
    element.append(
      el("span.tree-expander", {
        text: row.expandable ? (row.expanded ? "▾" : "▸") : "",
        onClick: (/** @type {Event} */ event) => {
          event.stopPropagation();
          if (row.expandable && row.depth > 0) {
            this.toggle(row.nodeId);
          }
        },
      }),
    );
    if (row.type === "port") {
      const port = row.port;
      element.classList.add("tree-port");
      element.append(
        el("span.tree-port-direction", { text: port.direction === "in" ? "→" : "←", title: `${port.direction}put` }),
        el("span.tree-label", { text: port.local_name }),
        el("span.tree-detail", { text: port.unit ?? "" }),
      );
      element.addEventListener("click", () => this.select(row.nodeId, false));
      return element;
    }

    const node = row.node;
    const kindClass = node.type === "driver" ? `tree-icon-driver-${node.kind}` : `tree-icon-${node.type}`;
    const problemLevel = app.validation.levelOf(node.id);
    element.append(
      el(`span.tree-icon.${kindClass}`),
      el(`span.tree-label${problemLevel && problemLevel !== "info" ? `.problem-text-${problemLevel}` : ""}`, {
        text: node.name,
      }),
      el("span.tree-detail", { text: node.type === "assembly" ? node.mode : (node.kind ?? "") }),
    );
    element.addEventListener("click", (event) => this.select(row.nodeId, event.ctrlKey || event.metaKey));
    element.addEventListener("dblclick", () => {
      if (Array.isArray(node.children)) {
        app.navigation.enter(node.id);
      } else {
        app.navigation.reveal(node.id);
        app.selection.set([node.id]);
        app.canvas.fit();
      }
    });
    element.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      if (node.id === app.store.rootId) {
        return;
      }
      if (!app.selection.has(node.id)) {
        this.select(node.id, false);
      }
      nodeMenu(app.canvas, node.id, event.clientX, event.clientY);
    });

    // Drag and drop to move nodes into another container.
    if (node.id !== app.store.rootId) {
      element.draggable = true;
      element.addEventListener("dragstart", (event) => {
        const ids = app.selection.has(node.id) ? app.selection.list() : [node.id];
        event.dataTransfer?.setData(DRAG_TYPE, JSON.stringify(ids));
      });
    }
    if (Array.isArray(node.children)) {
      element.addEventListener("dragover", (event) => {
        const types = event.dataTransfer?.types ?? [];
        if (types.includes(DRAG_TYPE) || types.includes(NEW_NODE_TYPE)) {
          event.preventDefault();
          element.classList.add("drop-target");
        }
      });
      element.addEventListener("dragleave", () => element.classList.remove("drop-target"));
      element.addEventListener("drop", (event) => {
        event.preventDefault();
        element.classList.remove("drop-target");
        const newNode = event.dataTransfer?.getData(NEW_NODE_TYPE);
        if (newNode) {
          app.store
            .execute({ type: "addNode", parent: node.id, node: JSON.parse(newNode) })
            .catch((error) => showError("The node could not be added", error));
          return;
        }
        const ids = JSON.parse(event.dataTransfer?.getData(DRAG_TYPE) || "[]");
        const placements = ids
          .filter((/** @type {string} */ id) => id !== node.id && app.store.node(id)?.parent !== node.id)
          .map((/** @type {string} */ id) => ({ id, parent: node.id }));
        if (placements.length) {
          app.store
            .execute({ type: "reparentNodes", placements })
            .catch((error) => showError("The nodes could not be moved", error));
        }
      });
    }
    return element;
  }
}
