// @ts-check
// Introspection state of each component: running, done or error.

export class ComponentStatus {
  /** @param {import("../lib/rpc.js").RpcClient} api */
  constructor(api) {
    /** @type {Map<string, {state: string, error: string}>} */
    this.states = new Map();
    /** @type {Set<(id: string) => void>} */
    this.listeners = new Set();
    api.on("component.status", ({ id, state, error }) => {
      this.states.set(id, { state, error });
      for (const listener of this.listeners) {
        listener(id);
      }
    });
    api.call("component.states").then((states) => {
      for (const [id, status] of Object.entries(states)) {
        this.states.set(id, /** @type {any} */ (status));
      }
    });
  }

  /** @param {string} id */
  get(id) {
    return this.states.get(id) ?? { state: "idle", error: "" };
  }

  /** @param {(id: string) => void} listener */
  onChange(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
