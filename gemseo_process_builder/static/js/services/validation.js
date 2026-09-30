// @ts-check
// The validation problems of the project, as computed by Python.

const LEVEL_RANK = { error: 0, warning: 1, info: 2 };

/**
 * @typedef {object} Problem
 * @property {string} key
 * @property {string} code
 * @property {"error" | "warning" | "info"} level
 * @property {string} message
 * @property {string} node
 * @property {string} port
 * @property {string} link
 * @property {string[]} quick_fixes
 */

export class ValidationState {
  /** @param {import("../lib/rpc.js").RpcClient} api */
  constructor(api) {
    /** @type {Problem[]} */
    this.problems = [];
    /** @type {Record<string, string>} */
    this.fixLabels = {};
    /** @type {Map<string, Problem[]>} */
    this.byNode = new Map();
    /** @type {Set<() => void>} */
    this.listeners = new Set();
    api.on("validation.updated", (state) => this.load(state));
    api.call("validation.state").then((state) => this.load(state));
  }

  /** @param {{problems: Problem[], fix_labels: Record<string, string>}} state */
  load(state) {
    this.problems = state.problems;
    this.fixLabels = state.fix_labels;
    this.byNode = new Map();
    for (const problem of this.problems) {
      if (problem.node) {
        const list = this.byNode.get(problem.node) ?? [];
        list.push(problem);
        this.byNode.set(problem.node, list);
      }
    }
    for (const listener of this.listeners) {
      listener();
    }
  }

  /**
   * The most severe level of the problems of a node, if any.
   *
   * @param {string} id
   * @returns {"error" | "warning" | "info" | null}
   */
  levelOf(id) {
    const problems = this.byNode.get(id) ?? [];
    let best = null;
    for (const problem of problems) {
      if (best === null || LEVEL_RANK[problem.level] < LEVEL_RANK[best]) {
        best = problem.level;
      }
    }
    return best;
  }

  /** @param {() => void} listener */
  onChange(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
