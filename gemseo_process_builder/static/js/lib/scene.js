// @ts-check
// What the workflow canvas draws for one level of the hierarchy: the nodes of
// the level (and the children of containers expanded in place), and the
// couplings between them, as resolved by Python (`resolve.level`).
import {
  CONTAINER_PADDING,
  HEADER_HEIGHT,
  NODE_WIDTH,
  boundingBox,
  cardAnchor,
  cardShape,
  gridPosition,
  nodeShape,
  portAnchor,
  sideAnchor,
  visiblePorts,
} from "./geometry.js";
import { labelPosition, routeLink } from "./link_routing.js";

const MAX_DEPTH = 6;
/** Beyond this number of variables, the couplings of a pair are one link. */
export const MAX_LINKS_PER_PAIR = 4;

/**
 * @typedef {object} LevelView - The result of `resolve.level`.
 * @property {string} level
 * @property {Record<string, {in: any, out: any}>} ports - Per child: for
 *   components, local name → global name; for containers, lists of global names.
 * @property {{source: string, target: string, feedback: boolean, variables: any[]}[]} edges
 * @property {string[]} free_inputs - Global names without a producer in the scope.
 */

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
 * @property {Set<string>} freeInputs - Shown input rows without a producer.
 */

/**
 * @typedef {object} SceneLink
 * @property {string} id
 * @property {string} from - Scene item drawn as the source.
 * @property {string} to - Scene item drawn as the target.
 * @property {string} path
 * @property {"explicit" | "implicit" | "aggregated"} kind
 * @property {boolean} feedback
 * @property {any[]} variables
 * @property {{x: number, y: number} | null} label - Where to write the count.
 * @property {string} sourcePort - Row name at the source ("" for side anchors).
 * @property {string} targetPort
 */

/**
 * Connected ports of every component, as "in:name" / "out:name" keys.
 *
 * @param {LevelView[]} views
 * @returns {Map<string, Set<string>>}
 */
export function connectedPorts(views) {
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
  for (const view of views) {
    for (const edge of view.edges) {
      for (const variable of edge.variables) {
        add(edge.source, `out:${variable.source_port || variable.name}`);
        add(edge.target, `in:${variable.target_port || variable.name}`);
      }
    }
  }
  return connected;
}

/**
 * The ports shown on a node: its own ports (components) or its derived ports
 * (containers), whose row names are global names.
 *
 * @param {any} node
 * @param {LevelView | undefined} view - The view of the node's parent level.
 * @returns {{local_name: string, direction: string}[]}
 */
function portsOf(node, view) {
  if (!Array.isArray(node.children)) {
    return node.ports ?? [];
  }
  const derived = view?.ports[node.id];
  if (!derived) {
    return [];
  }
  return [
    ...derived.in.map((/** @type {string} */ name) => ({ local_name: name, direction: "in" })),
    ...derived.out.map((/** @type {string} */ name) => ({ local_name: name, direction: "out" })),
  ];
}

/**
 * Build the scene of a level.
 *
 * @param {import("./patch.js").DocumentState} state
 * @param {string} levelId - The container whose content is shown.
 * @param {Map<string, {x: number, y: number}>} [overrides] - Positions replacing
 *   the stored ones (nodes being dragged), in their container's coordinates.
 * @param {Map<string, LevelView>} [views] - Resolved couplings of the level and
 *   of the containers expanded in place, by container id.
 * @param {boolean} [expandAll] - Expand every container in place (image export
 *   of the whole model).
 * @returns {{items: SceneItem[], links: SceneLink[], box: import("./geometry.js").Rect | null}}
 */
export function buildScene(state, levelId, overrides = new Map(), views = new Map(), expandAll = false) {
  /** @type {SceneItem[]} */
  const items = [];
  const connected = connectedPorts([...views.values()]);
  // The free inputs of each view, as a set built once: a level has thousands.
  /** @type {Map<LevelView | undefined, Set<string>>} */
  const freeSets = new Map();
  /** @param {LevelView | undefined} view */
  const freeInputsOf = (view) => {
    let free = freeSets.get(view);
    if (!free) {
      free = new Set(view?.free_inputs ?? []);
      freeSets.set(view, free);
    }
    return free;
  };

  /**
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
    const view = views.get(containerId);
    for (const childId of state.nodes[containerId]?.children ?? []) {
      const node = state.nodes[childId];
      if (!node) {
        continue;
      }
      const layout = state.layout[childId];
      const stored = layout ? { x: layout.x, y: layout.y } : gridPosition(unplaced++);
      const position = overrides.get(childId) ?? stored;
      const item = placeNode(node, layout, offsetX + position.x, offsetY + position.y, depth, containerId, view);
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
   * @param {LevelView | undefined} view
   * @returns {SceneItem}
   */
  const placeNode = (node, layout, x, y, depth, parent, view) => {
    const container = Array.isArray(node.children);
    const expanded = container && (expandAll || layout?.expanded === true) && depth < MAX_DEPTH;
    const all = portsOf(node, view);
    // Nodes are cards by default; their variables can be listed on demand.
    const mode = layout?.port_display ?? "compact";
    const shape =
      mode === "compact" || mode === "none"
        ? cardShape({
            inputs: all.filter((port) => port.direction === "in").length,
            outputs: all.filter((port) => port.direction === "out").length,
          })
        : nodeShape(visiblePorts(all, mode, connected.get(node.id) ?? new Set()));
    const free = freeInputsOf(view);
    const globals = container ? null : view?.ports[node.id]?.in;
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
      freeInputs: new Set(
        shape.inputs.map((row) => row.name).filter((name) => free.has(globals ? globals[name] : name)),
      ),
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

  /** @type {SceneLink[]} */
  const links = [];
  for (const [viewLevel, view] of views) {
    for (const edge of view.edges) {
      const from = byId.get(edge.source);
      const to = byId.get(edge.target);
      if (!from || !to || (viewLevel !== levelId && !byId.get(viewLevel)?.expanded)) {
        continue;
      }
      const bottom = Math.max(from.y + from.height, to.y + to.height);
      // One link per pair of nodes when one is a card, or when they share many variables.
      if (edge.variables.length > MAX_LINKS_PER_PAIR || from.shape.card || to.shape.card) {
        const start = from.shape.card ? cardAnchor(from, "out") : sideAnchor(from, "out");
        const end = to.shape.card ? cardAnchor(to, "in") : sideAnchor(to, "in");
        const single = edge.variables.length === 1 ? edge.variables[0] : null;
        links.push({
          id: `${viewLevel}:${edge.source}>${edge.target}`,
          from: from.id,
          to: to.id,
          path: routeLink(start, end, { feedback: edge.feedback, bottom }),
          kind: single ? (single.explicit ? "explicit" : "implicit") : "aggregated",
          feedback: edge.feedback,
          variables: edge.variables,
          label: single ? null : labelPosition(start, end),
          sourcePort: "",
          targetPort: "",
        });
        continue;
      }
      for (const variable of edge.variables) {
        const sourcePort = from.container ? variable.name : variable.source_port;
        const targetPort = to.container ? variable.name : variable.target_port;
        const start = portAnchor(from, from.shape, "out", sourcePort) ?? sideAnchor(from, "out");
        const end = portAnchor(to, to.shape, "in", targetPort) ?? sideAnchor(to, "in");
        links.push({
          id: `${viewLevel}:${edge.source}>${edge.target}:${variable.name}`,
          from: from.id,
          to: to.id,
          path: routeLink(start, end, { feedback: edge.feedback, bottom }),
          kind: variable.explicit ? "explicit" : "implicit",
          feedback: edge.feedback,
          variables: [variable],
          label: null,
          sourcePort,
          targetPort,
        });
      }
    }
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

/**
 * The containers whose couplings the scene needs: the level and the
 * containers expanded in place inside it.
 *
 * @param {import("./patch.js").DocumentState} state
 * @param {string} levelId
 * @param {boolean} [expandAll] - Every container is expanded in place.
 * @returns {string[]}
 */
export function levelsToResolve(state, levelId, expandAll = false) {
  const levels = [levelId];
  /**
   * @param {string} id
   * @param {number} depth
   */
  const visit = (id, depth) => {
    for (const childId of state.nodes[id]?.children ?? []) {
      const child = state.nodes[childId];
      if (child?.children && (expandAll || state.layout[childId]?.expanded) && depth < MAX_DEPTH) {
        levels.push(childId);
        visit(childId, depth + 1);
      }
    }
  };
  visit(levelId, 0);
  return levels;
}
