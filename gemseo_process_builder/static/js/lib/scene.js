// @ts-check
// What the workflow canvas draws for one level of the hierarchy: the nodes of
// the level (and the children of containers expanded in place), and the links.
import {
  CONTAINER_PADDING,
  HEADER_HEIGHT,
  NODE_WIDTH,
  boundingBox,
  gridPosition,
  linkPath,
  nodeShape,
  portAnchor,
  sideAnchor,
  visiblePorts,
} from "./geometry.js";

const MAX_DEPTH = 6;

/**
 * @typedef {object} SceneItem
 * @property {string} id
 * @property {any} node - The node entity.
 * @property {boolean} container
 * @property {boolean} expanded - A container showing its children in place.
 * @property {number} x - Top-left corner, in canvas coordinates.
 * @property {number} y
 * @property {{x: number, y: number}} local - Position stored in the layout,
 *   relative to the container holding the node.
 * @property {number} width
 * @property {number} height
 * @property {import("./geometry.js").NodeShape} shape - Header and port rows.
 * @property {number} depth - 0 for the nodes of the level.
 * @property {string} parent - The container holding the node.
 */

/**
 * @typedef {object} SceneLink
 * @property {string} id
 * @property {string} from - Scene item drawn as the source.
 * @property {string} to - Scene item drawn as the target.
 * @property {string} path
 * @property {any} link
 */

/**
 * Connected ports of every node, as "in:name" / "out:name" keys.
 *
 * @param {Record<string, any>} links
 * @returns {Map<string, Set<string>>}
 */
export function connectedPorts(links) {
  /** @type {Map<string, Set<string>>} */
  const connected = new Map();
  /**
   * @param {string} node
   * @param {string} key
   */
  const add = (node, key) => {
    if (!connected.has(node)) {
      connected.set(node, new Set());
    }
    connected.get(node)?.add(key);
  };
  for (const link of Object.values(links)) {
    add(link.source.node, `out:${link.source.port}`);
    add(link.target.node, `in:${link.target.port}`);
  }
  return connected;
}

/**
 * Build the scene of a level.
 *
 * @param {import("./patch.js").DocumentState} state
 * @param {string} levelId - The container whose content is shown.
 * @param {Map<string, {x: number, y: number}>} [overrides] - Positions replacing
 *   the stored ones (nodes being dragged), in their container's coordinates.
 * @returns {{items: SceneItem[], links: SceneLink[], box: import("./geometry.js").Rect | null}}
 */
export function buildScene(state, levelId, overrides = new Map()) {
  /** @type {SceneItem[]} */
  const items = [];
  const connected = connectedPorts(state.links);

  /**
   * Place the children of a container and return their bounding box.
   *
   * @param {string} containerId
   * @param {number} offsetX
   * @param {number} offsetY
   * @param {number} depth
   * @returns {SceneItem[]}
   */
  const placeChildren = (containerId, offsetX, offsetY, depth) => {
    /** @type {SceneItem[]} */
    const placed = [];
    let unplaced = 0;
    for (const childId of state.nodes[containerId]?.children ?? []) {
      const node = state.nodes[childId];
      if (!node) {
        continue;
      }
      const layout = state.layout[childId];
      const stored = layout ? { x: layout.x, y: layout.y } : gridPosition(unplaced++);
      const position = overrides.get(childId) ?? stored;
      const item = placeNode(node, layout, offsetX + position.x, offsetY + position.y, depth, containerId);
      item.local = { x: position.x, y: position.y };
      placed.push(item);
    }
    return placed;
  };

  /**
   * @param {any} node
   * @param {any} layout
   * @param {number} x
   * @param {number} y
   * @param {number} depth
   * @param {string} parent
   * @returns {SceneItem}
   */
  const placeNode = (node, layout, x, y, depth, parent) => {
    const container = Array.isArray(node.children);
    const expanded = container && layout?.expanded === true && depth < MAX_DEPTH;
    const ports = container
      ? { inputs: [], outputs: [], hidden: 0 }
      : visiblePorts(node.ports ?? [], layout?.port_display ?? "all", connected.get(node.id) ?? new Set());
    const shape = nodeShape(ports);
    /** @type {SceneItem} */
    const item = {
      id: node.id,
      node,
      container,
      expanded,
      x,
      y,
      local: { x: 0, y: 0 },
      width: shape.width,
      height: shape.height,
      shape,
      depth,
      parent,
    };
    items.push(item);
    if (expanded) {
      const inner = placeChildren(node.id, x + CONTAINER_PADDING, y + HEADER_HEIGHT + CONTAINER_PADDING, depth + 1);
      const box = boundingBox(inner);
      if (box) {
        item.width = Math.max(NODE_WIDTH, box.x + box.width + CONTAINER_PADDING - x);
        item.height = Math.max(shape.height, box.y + box.height + CONTAINER_PADDING - y);
      }
    }
    return item;
  };

  const topLevel = placeChildren(levelId, 0, 0, 0);
  const byId = new Map(items.map((item) => [item.id, item]));

  /**
   * The scene item standing for a node: itself, or its closest visible ancestor.
   *
   * @param {string} nodeId
   * @returns {SceneItem | undefined}
   */
  const visibleItem = (nodeId) => {
    let current = state.nodes[nodeId];
    while (current && current.id !== levelId) {
      const item = byId.get(current.id);
      if (item) {
        return item;
      }
      current = current.parent ? state.nodes[current.parent] : null;
    }
    return undefined;
  };

  /** @type {SceneLink[]} */
  const links = [];
  for (const link of Object.values(state.links)) {
    const from = visibleItem(link.source.node);
    const to = visibleItem(link.target.node);
    if (!from || !to || from === to) {
      continue;
    }
    const start =
      (from.id === link.source.node && portAnchor(from, from.shape, "out", link.source.port)) ||
      sideAnchor(from, "out");
    const end =
      (to.id === link.target.node && portAnchor(to, to.shape, "in", link.target.port)) || sideAnchor(to, "in");
    links.push({ id: link.id, from: from.id, to: to.id, path: linkPath(start, end), link });
  }

  return { items, links, box: boundingBox(topLevel) };
}

/**
 * Rectangles of the nodes of the level itself (for rectangle selection).
 *
 * @param {SceneItem[]} items
 * @returns {Map<string, import("./geometry.js").Rect>}
 */
export function topLevelRects(items) {
  return new Map(items.filter((item) => item.depth === 0).map((item) => [item.id, item]));
}
