// @ts-check
// The page's mirror of the document, kept up to date by Python's patches.
import { applyChanges, checkRevision, childrenOf, emptyState, fromSnapshot, pathTo } from "./lib/patch.js";

/**
 * @typedef {object} StoreEvent
 * @property {"patch" | "reset"} type
 * @property {Set<string>} touched - "kind:id" keys; empty for a reset.
 */

export class DocumentStore {
  /** @param {import("./lib/rpc.js").RpcClient} api */
  constructor(api) {
    this.api = api;
    this.state = emptyState();
    /** @type {Set<(event: StoreEvent) => void>} */
    this.listeners = new Set();
    this.resyncing = false;
    api.on("document.patch", (patch) => this.onPatch(patch));
    api.on("document.reset", (snapshot) => this.load(snapshot));
  }

  /** Load the whole document from Python. */
  async reload() {
    this.resyncing = true;
    try {
      this.load(await this.api.call("doc.snapshot"));
    } finally {
      this.resyncing = false;
    }
  }

  /** @param {any} snapshot */
  load(snapshot) {
    this.state = fromSnapshot(snapshot);
    this.emit({ type: "reset", touched: new Set() });
  }

  /** @param {{rev: number, changes: import("./lib/patch.js").Change[]}} patch */
  onPatch(patch) {
    const status = checkRevision(this.state.rev, patch.rev);
    if (status === "stale") {
      return;
    }
    if (status === "gap") {
      console.warn(`Document revision gap (${this.state.rev} → ${patch.rev}): reloading.`);
      if (!this.resyncing) {
        this.reload();
      }
      return;
    }
    const touched = applyChanges(this.state, patch.changes);
    this.state.rev = patch.rev;
    this.emit({ type: "patch", touched });
  }

  /** @param {StoreEvent} event */
  emit(event) {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (error) {
        console.error("Document listener failed:", error);
      }
    }
  }

  /**
   * @param {(event: StoreEvent) => void} listener
   * @returns {() => void}
   */
  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  get rev() {
    return this.state.rev;
  }

  get rootId() {
    return this.state.root;
  }

  /** @param {string} id */
  node(id) {
    return this.state.nodes[id];
  }

  /** @param {string} id */
  children(id) {
    return childrenOf(this.state, id);
  }

  /** @param {string} id */
  layoutOf(id) {
    return this.state.layout[id];
  }

  /** @param {string} id */
  pathTo(id) {
    return pathTo(this.state, id);
  }

  /**
   * Send a command to Python.
   *
   * @param {object} command
   * @param {{undoable?: boolean}} [options]
   */
  execute(command, { undoable = true } = {}) {
    return this.api.call("doc.execute", { command, undoable });
  }

  /**
   * Send several commands forming one undo step.
   *
   * @param {object[]} commands
   * @param {string} label
   */
  executeMany(commands, label) {
    return this.api.call("doc.executeMany", { commands, label });
  }
}
