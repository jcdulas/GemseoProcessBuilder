// @ts-check
// Where the derivatives of each component come from (exact, approximated or
// missing), and the last check of the derivatives of each node.

/** Wait after a change of the model before asking again: scripts are built. */
const DELAY_MS = 1500;

/**
 * @typedef {object} DerivativeCheck - The result of `derivatives.check`.
 * @property {string} node
 * @property {string} name
 * @property {string} discipline
 * @property {string} origin
 * @property {string} mode
 * @property {string[]} inputs
 * @property {string[]} outputs
 * @property {{output: string, input: string, error: number, size: number, ok: boolean}[]} pairs
 * @property {number} tolerance
 * @property {boolean} ok
 * @property {boolean} limited
 * @property {string[]} notes
 * @property {number} seconds
 */

export class DerivativeState {
  /** @param {import("../lib/rpc.js").RpcClient} api */
  constructor(api) {
    this.api = api;
    /** @type {Map<string, string>} */
    this.origins = new Map();
    /** @type {Map<string, DerivativeCheck>} */
    this.checks = new Map();
    /** @type {Set<() => void>} */
    this.listeners = new Set();
    /** @type {any} */
    this.timer = null;
    this.request = 0;
    // The origins change with the model; the checks are then out of date.
    api.on("resolution.updated", () => {
      this.checks.clear();
      this.schedule();
    });
    api.on("document.reset", () => {
      this.origins.clear();
      this.checks.clear();
      this.notify();
      this.schedule();
    });
    this.schedule();
  }

  schedule() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.refresh(), DELAY_MS);
  }

  async refresh() {
    const request = ++this.request;
    try {
      const { origins } = await this.api.call("derivatives.origins", {}, { timeout: 180_000 });
      if (request === this.request) {
        this.origins = new Map(Object.entries(origins));
        this.notify();
      }
    } catch (error) {
      // The worker may still be starting: try again later.
      console.debug("The origins of the derivatives are not known yet:", error);
      this.timer = setTimeout(() => this.refresh(), 5 * DELAY_MS);
    }
  }

  /**
   * Compare the derivatives of a node with finite differences, in the worker.
   *
   * @param {string} id
   * @returns {Promise<DerivativeCheck>}
   */
  async check(id) {
    const result = await this.api.call("derivatives.check", { node: id }, { timeout: 600_000 });
    this.checks.set(id, result);
    this.notify();
    return result;
  }

  /**
   * What the card of a node shows.
   *
   * @param {string} id
   * @returns {{origin: string, check: boolean | null}}
   */
  of(id) {
    const check = this.checks.get(id);
    return { origin: this.origins.get(id) ?? "", check: check ? check.ok : null };
  }

  notify() {
    for (const listener of this.listeners) {
      listener();
    }
  }

  /** @param {() => void} listener */
  onChange(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
