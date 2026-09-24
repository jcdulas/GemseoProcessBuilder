// @ts-check
// The selected nodes, shared by the canvas, the tree and the inspector.

export class Selection {
  constructor() {
    /** @type {Set<string>} */
    this.ids = new Set();
    /** @type {Set<(ids: Set<string>) => void>} */
    this.listeners = new Set();
  }

  /** @returns {string[]} */
  list() {
    return [...this.ids];
  }

  /** @param {string} id */
  has(id) {
    return this.ids.has(id);
  }

  get size() {
    return this.ids.size;
  }

  /** @param {Iterable<string>} ids */
  set(ids) {
    const next = new Set(ids);
    if (next.size === this.ids.size && [...next].every((id) => this.ids.has(id))) {
      return;
    }
    this.ids = next;
    this.emit();
  }

  /** @param {string} id */
  toggle(id) {
    const next = new Set(this.ids);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    this.set(next);
  }

  /** @param {Iterable<string>} ids */
  add(ids) {
    this.set([...this.ids, ...ids]);
  }

  clear() {
    this.set([]);
  }

  /**
   * Drop the ids that no longer exist.
   *
   * @param {(id: string) => boolean} exists
   */
  prune(exists) {
    this.set(this.list().filter(exists));
  }

  emit() {
    for (const listener of this.listeners) {
      listener(this.ids);
    }
  }

  /**
   * @param {(ids: Set<string>) => void} listener
   * @returns {() => void}
   */
  onChange(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
