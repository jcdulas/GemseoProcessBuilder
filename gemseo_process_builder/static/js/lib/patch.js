// @ts-check
// The flat mirror of the document and the application of Python's patches.

/**
 * @typedef {object} DocumentState
 * @property {number} rev
 * @property {string | null} root
 * @property {Record<string, any>} nodes - Node entities; containers list child ids.
 * @property {Record<string, any>} links
 * @property {Record<string, any>} layout - Node layouts by node id.
 * @property {Record<string, any>} levels - Canvas zoom and pan by container id.
 * @property {Record<string, any>} view - Free view state.
 * @property {Record<string, any>} project - Metadata and settings.
 */

/**
 * @typedef {object} Change
 * @property {"upsert" | "delete"} op
 * @property {"node" | "link" | "layout" | "level" | "view" | "project"} kind
 * @property {string} id
 * @property {any} [data]
 */

/** The collection holding each kind of entity. */
export const COLLECTIONS = {
  node: "nodes",
  link: "links",
  layout: "layout",
  level: "levels",
  view: "view",
  project: "project",
};

/** @returns {DocumentState} */
export function emptyState() {
  return { rev: 0, root: null, nodes: {}, links: {}, layout: {}, levels: {}, view: {}, project: {} };
}

/**
 * Build the state from a `doc.snapshot` result.
 *
 * @param {any} snapshot
 * @returns {DocumentState}
 */
export function fromSnapshot(snapshot) {
  return {
    rev: snapshot.rev,
    root: snapshot.root,
    nodes: { ...snapshot.nodes },
    links: { ...snapshot.links },
    layout: { ...snapshot.layout },
    levels: { ...snapshot.levels },
    view: { ...snapshot.view },
    project: { ...snapshot.project },
  };
}

/**
 * How a patch relates to the current revision.
 *
 * @param {number} current
 * @param {number} incoming
 * @returns {"apply" | "stale" | "gap"}
 */
export function checkRevision(current, incoming) {
  if (incoming === current + 1) {
    return "apply";
  }
  return incoming <= current ? "stale" : "gap";
}

/**
 * Apply changes to a state, in place.
 *
 * @param {DocumentState} state
 * @param {Change[]} changes
 * @returns {Set<string>} The keys "kind:id" of the changed entities.
 */
export function applyChanges(state, changes) {
  const touched = new Set();
  for (const change of changes) {
    const collection = /** @type {Record<string, any>} */ (
      state[/** @type {keyof DocumentState} */ (COLLECTIONS[change.kind])]
    );
    if (!collection) {
      throw new Error(`Unknown entity kind ${change.kind}`);
    }
    if (change.op === "delete") {
      delete collection[change.id];
    } else {
      collection[change.id] = change.data;
    }
    touched.add(`${change.kind}:${change.id}`);
  }
  return touched;
}

/**
 * The children entities of a container, in order.
 *
 * @param {DocumentState} state
 * @param {string} id
 * @returns {any[]}
 */
export function childrenOf(state, id) {
  return (state.nodes[id]?.children ?? []).map((/** @type {string} */ child) => state.nodes[child]).filter(Boolean);
}

/**
 * The ids from the root to a node, both included.
 *
 * @param {DocumentState} state
 * @param {string} id
 * @returns {string[]}
 */
export function pathTo(state, id) {
  const path = [];
  let current = state.nodes[id];
  while (current) {
    path.unshift(current.id);
    current = current.parent ? state.nodes[current.parent] : null;
  }
  return path;
}

/**
 * The links touching a set of nodes.
 *
 * @param {DocumentState} state
 * @param {Set<string>} nodeIds
 * @returns {any[]}
 */
export function linksOf(state, nodeIds) {
  return Object.values(state.links).filter(
    (link) => nodeIds.has(link.source.node) || nodeIds.has(link.target.node),
  );
}
