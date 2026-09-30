// @ts-check
// The level of the hierarchy shown by the workflow canvas.

export class Navigation {
  /** @param {import("../store.js").DocumentStore} store */
  constructor(store) {
    this.store = store;
    /** @type {string | null} */
    this.level = null;
    /** @type {Set<(level: string) => void>} */
    this.listeners = new Set();
  }

  /** The level shown, falling back to the root when it no longer exists. */
  current() {
    if (!this.level || !this.store.node(this.level)?.children) {
      this.level = this.store.rootId;
    }
    return /** @type {string} */ (this.level);
  }

  /**
   * Show the content of a container.
   *
   * @param {string} id
   */
  enter(id) {
    if (!this.store.node(id)?.children || id === this.level) {
      return;
    }
    this.level = id;
    this.emit();
  }

  /** Go to the parent level. Returns whether it moved. */
  up() {
    const parent = this.store.node(this.current())?.parent;
    if (!parent) {
      return false;
    }
    this.level = parent;
    this.emit();
    return true;
  }

  /**
   * Show the level containing a node.
   *
   * @param {string} id
   */
  reveal(id) {
    const parent = this.store.node(id)?.parent;
    if (parent) {
      this.enter(parent);
    }
  }

  emit() {
    for (const listener of this.listeners) {
      listener(this.current());
    }
  }

  /** @param {(level: string) => void} listener */
  onChange(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
