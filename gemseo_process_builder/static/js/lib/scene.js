// @ts-check
// What the workflow canvas draws for one level of the hierarchy: the nodes of
// the level (and the children of containers expanded in place), and the
// couplings between them, as resolved by Python (`resolve.level`).
// A driver is a tile of the workflow: the nodes it drives are drawn next to it,
// at the same level and in the same coordinates, linked to it by the variables
// it sends and gets back.
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
import { driverLinks } from "./driver_links.js";
import { labelPosition, routeLink } from "./link_routing.js";
import { nodeAppearance } from "./node_icons.js";

const MAX_DEPTH = 6;
/** Beyond this number of variables, the couplings of a pair are one link. */
export const MAX_LINKS_PER_PAIR = 4;
/** Space kept between a driver tile and the nodes it drives, when it is moved aside. */
export const TILE_GAP = 80;

/**
 * Whether a node is drawn as a driver tile, next to the nodes it drives.
 *
 * @param {any} node
 * @returns {boolean}
 */
export function isTile(node) {
  return node?.type === "driver";
}

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
 * @property {boolean} tile - A driver drawn as a tile, next to the nodes it drives.
 * @property {number} x - Top-left corner, in canvas coordinates.
 * @property {number} y
 * @property {{x: number, y: number}} local - Position stored in the layout,
 *   relative to the container holding the node.
 * @property {number} width
 * @property {number} height
 * @property {import("./geometry.js").NodeShape} shape - Header and port rows.
 * @property {number} depth - 0 for the nodes of the level (and the nodes
 *   their drivers drive, drawn at the same level).
 * @property {string} parent - The container holding the node.
 * @property {Set<string>} freeInputs - Shown input rows without a producer.
 */

/**
 * @typedef {object} SceneLink
 * @property {string} id
 * @property {string} from - Scene item drawn as the source.
 * @property {string} to - Scene item drawn as the target.
 * @property {string} path
 * @property {"explicit" | "implicit" | "aggregated" | "driver" | "control"} kind -
 *   driver: variables between a driver and a node it drives; control: a driven
 *   node exchanging no variable with its driver.
 * @property {boolean} feedback
 * @property {any[]} variables
 * @property {{x: number, y: number} | null} label - Where to write the count.
 * @property {string} sourcePort - Row name at the source ("" for side anchors).
 * @property {string} targetPort
 * @property {string} [driver] - For driver and control links: the driver.
 * @property {string} [tone] - For driver and control links: the color family of the driver.
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
   * @param {number} offsetX - Where the coordinates of the children start.
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
      if (item.tile) {
        // The nodes a driver drives are at the same level, in the same coordinates.
        const driven = placeChildren(node.id, offsetX, offsetY, depth);
        placed.push(...driven);
        moveAside(item, driven, offsetX, offsetY);
      }
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
    const tile = isTile(node) && depth < MAX_DEPTH;
    const expanded = container && !tile && (expandAll || layout?.expanded === true) && depth < MAX_DEPTH;
    const all = portsOf(node, view);
    // Nodes are cards by default; their variables can be listed on demand.
    // A tile has a link point on each side: its variables go to its nodes.
    const mode = tile ? "compact" : (layout?.port_display ?? "compact");
    const shape =
      mode === "compact" || mode === "none"
        ? cardShape(
            tile
              ? { inputs: 1, outputs: 1 }
              : {
                  inputs: all.filter((port) => port.direction === "in").length,
                  outputs: all.filter((port) => port.direction === "out").length,
                },
          )
        : nodeShape(visiblePorts(all, mode, connected.get(node.id) ?? new Set()));
    const free = freeInputsOf(view);
    const globals = container ? null : view?.ports[node.id]?.in;
    /** @type {SceneItem} */
    const item = {
      id: node.id,
      node,
      container,
      expanded,
      tile,
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

  /**
   * A tile over the nodes it drives (a project laid out before tiles, where
   * they had their own level) is shown on their left.
   *
   * @param {SceneItem} tile
   * @param {SceneItem[]} driven
   * @param {number} offsetX
   * @param {number} offsetY
   */
  const moveAside = (tile, driven, offsetX, offsetY) => {
    const box = boundingBox(driven);
    if (!box || overrides.has(tile.id) || !overlaps(tile, box)) {
      return;
    }
    tile.x = box.x - tile.width - TILE_GAP;
    tile.y = box.y + box.height / 2 - tile.height / 2;
    tile.local = { x: tile.x - offsetX, y: tile.y - offsetY };
  };

  const topLevel = placeChildren(levelId, 0, 0, 0).filter((item) => item.depth === 0);
  const byId = new Map(items.map((item) => [item.id, item]));

  /** @type {SceneLink[]} */
  const links = [];
  for (const [viewLevel, view] of views) {
    for (const edge of view.edges) {
      const from = byId.get(edge.source);
      const to = byId.get(edge.target);
      const shown = viewLevel === levelId || byId.get(viewLevel)?.expanded || byId.get(viewLevel)?.tile;
      if (!from || !to || !shown) {
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

  for (const item of items) {
    if (item.tile) {
      links.push(...tileLinks(item, state, views.get(item.id), byId));
    }
  }

  return { items, links, box: boundingBox(topLevel) };
}

/**
 * Whether a rectangle overlaps another one.
 *
 * @param {import("./geometry.js").Rect} a
 * @param {import("./geometry.js").Rect} b
 */
function overlaps(a, b) {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

/**
 * The links of a driver tile to the nodes it drives. Results come back to the
 * input side of the tile, closing the loop of the driver.
 *
 * @param {SceneItem} tile
 * @param {import("./patch.js").DocumentState} state
 * @param {LevelView | undefined} view - The view of the scope of the driver.
 * @param {Map<string, SceneItem>} byId
 * @returns {SceneLink[]}
 */
function tileLinks(tile, state, view, byId) {
  const node = tile.node;
  const driver = { id: node.id, kind: node.kind, config: node.config ?? {}, children: node.children ?? [] };
  /** @type {SceneLink[]} */
  const links = [];
  for (const link of driverLinks(driver, view)) {
    const from = byId.get(link.source);
    const to = byId.get(link.target);
    if (!from || !to) {
      continue;
    }
    const start = from.shape.card ? cardAnchor(from, "out") : sideAnchor(from, "out");
    const end = to.shape.card ? cardAnchor(to, "in") : sideAnchor(to, "in");
    // A result going back to the driver loops under the nodes, like a feedback.
    const back = link.target === tile.id && start.x > end.x;
    links.push({
      id: `driver:${link.source}>${link.target}`,
      from: from.id,
      to: to.id,
      path: routeLink(start, end, { feedback: back, bottom: Math.max(from.y + from.height, to.y + to.height) }),
      kind: link.control ? "control" : "driver",
      feedback: false,
      variables: link.variables,
      label: link.variables.length > 1 ? labelPosition(start, end) : null,
      sourcePort: "",
      targetPort: "",
      driver: tile.id,
      tone: nodeAppearance(node).tone,
    });
  }
  return links;
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
 * The containers whose couplings the scene needs: the level, the drivers
 * drawn as tiles and the containers expanded in place inside it.
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
      const shown = isTile(child) || expandAll || state.layout[childId]?.expanded;
      if (child?.children && shown && depth < MAX_DEPTH) {
        levels.push(childId);
        visit(childId, depth + 1);
      }
    }
  };
  visit(levelId, 0);
  return levels;
}
