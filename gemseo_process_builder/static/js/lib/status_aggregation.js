// @ts-check
// Execution states of containers, from the states of their components.

/** @typedef {"pending" | "running" | "done" | "failed"} RunState */

/**
 * The state of a container from the states of its children.
 *
 * Failed if any child failed; running if any runs, or if some are done while
 * others wait; done when all are done; pending when all wait.
 *
 * @param {(RunState | null)[]} states - ``null`` for children without a state.
 * @returns {RunState | null}
 */
export function aggregateState(states) {
  const known = states.filter((state) => state !== null);
  if (!known.length) {
    return null;
  }
  if (known.includes("failed")) {
    return "failed";
  }
  if (known.includes("running")) {
    return "running";
  }
  if (known.every((state) => state === "done")) {
    return "done";
  }
  return known.includes("done") ? "running" : "pending";
}

/**
 * The state of every node: components from the run, containers aggregated.
 *
 * @param {string} rootId
 * @param {(id: string) => string[] | null} childrenOf - ``null`` for components.
 * @param {Map<string, RunState>} componentStates
 * @returns {Map<string, RunState>}
 */
export function nodeStates(rootId, childrenOf, componentStates) {
  /** @type {Map<string, RunState>} */
  const states = new Map();
  /**
   * @param {string} id
   * @returns {RunState | null}
   */
  const visit = (id) => {
    const children = childrenOf(id);
    const state = children ? aggregateState(children.map(visit)) : (componentStates.get(id) ?? null);
    if (state) {
      states.set(id, state);
    }
    return state;
  };
  visit(rootId);
  return states;
}
