// @ts-check
// The model tree as a flat list of visible rows.

/**
 * @typedef {object} TreeRow
 * @property {string} key - Unique row key: a node id, or "<node id>/<in|out>/<port>".
 * @property {"node" | "port"} type
 * @property {string} nodeId
 * @property {number} depth
 * @property {boolean} expandable
 * @property {boolean} expanded
 * @property {any} [node]
 * @property {any} [port]
 */

/**
 * Flatten the tree below the root, following the expanded set.
 * Components are expandable to show their variables.
 *
 * @param {import("./patch.js").DocumentState} state
 * @param {Set<string>} expanded
 * @returns {TreeRow[]}
 */
export function flattenTree(state, expanded) {
  /** @type {TreeRow[]} */
  const rows = [];
  /**
   * @param {string} id
   * @param {number} depth
   */
  const visit = (id, depth) => {
    const node = state.nodes[id];
    if (!node) {
      return;
    }
    const container = Array.isArray(node.children);
    const ports = node.ports ?? [];
    const expandable = container ? node.children.length > 0 : ports.length > 0;
    const isExpanded = expandable && (expanded.has(id) || depth === 0);
    rows.push({ key: id, type: "node", nodeId: id, depth, expandable, expanded: isExpanded, node });
    if (!isExpanded) {
      return;
    }
    if (container) {
      for (const child of node.children) {
        visit(child, depth + 1);
      }
    } else {
      for (const port of ports) {
        rows.push({
          key: `${id}/${port.direction}/${port.local_name}`,
          type: "port",
          nodeId: id,
          depth: depth + 1,
          expandable: false,
          expanded: false,
          port,
        });
      }
    }
  };
  if (state.root) {
    visit(state.root, 0);
  }
  return rows;
}

/**
 * The ancestors to expand so that a node becomes visible.
 *
 * @param {import("./patch.js").DocumentState} state
 * @param {string} id
 * @returns {string[]}
 */
export function ancestorsToReveal(state, id) {
  const ancestors = [];
  let parent = state.nodes[id]?.parent;
  while (parent) {
    ancestors.push(parent);
    parent = state.nodes[parent]?.parent;
  }
  return ancestors;
}
