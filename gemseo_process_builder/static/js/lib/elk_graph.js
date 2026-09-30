// @ts-check
// Pure helpers of the auto-layout: a level of the canvas as an ELK graph, and
// the positions ELK computes back as layout positions.

/** ELK's layered algorithm, left to right, with room for the links. */
export const LAYOUT_OPTIONS = {
  "elk.algorithm": "layered",
  "elk.direction": "RIGHT",
  "elk.spacing.nodeNode": "40",
  "elk.layered.spacing.nodeNodeBetweenLayers": "90",
  "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
  "elk.layered.cycleBreaking.strategy": "GREEDY",
  "elk.edgeRouting": "ORTHOGONAL",
};

/** Above this many nodes, a level is laid out without its ports. */
export const LARGE_LEVEL = 100;

/**
 * Options for large levels: only the nodes and one edge per pair of them, no
 * edge routing (only the positions of the nodes are used), simple placement,
 * and crossings reduced from the current order of the nodes. Measured on
 * 300 nodes and 2,287 edges: about 1 s, against 10 s with the options of small
 * levels.
 */
export const LARGE_LAYOUT_OPTIONS = {
  ...LAYOUT_OPTIONS,
  "elk.edgeRouting": "POLYLINE",
  "elk.layered.thoroughness": "1",
  "elk.layered.crossingMinimization.greedySwitch.type": "OFF",
  "elk.layered.crossingMinimization.strategy": "INTERACTIVE",
  "elk.layered.nodePlacement.strategy": "SIMPLE",
  "elk.separateConnectedComponents": "false",
};

/**
 * The id of a port in the ELK graph.
 *
 * @param {string} node
 * @param {"in" | "out"} direction
 * @param {string} name
 */
export function portId(node, direction, name) {
  return `${node}|${direction}|${name}`;
}

/**
 * The ELK graph of nodes of one level and of the links between them.
 *
 * Ports keep their exact place on the node (``FIXED_POS``): inputs on the
 * left, outputs on the right, so that ELK orders the nodes to avoid crossings.
 * Large levels (``LARGE_LEVEL``) are laid out without ports.
 *
 * @param {{id: string, width: number, height: number, shape: import("./geometry.js").NodeShape}[]} items
 * @param {{id: string, from: string, to: string, sourcePort: string, targetPort: string}[]} links
 */
export function toElkGraph(items, links) {
  if (items.length > LARGE_LEVEL) {
    return largeElkGraph(items, links);
  }
  const ids = new Set(items.map((item) => item.id));
  /** @type {Set<string>} */
  const ports = new Set();
  const children = items.map((item) => {
    const inputs = item.shape.inputs.map((row) => ({
      id: portId(item.id, "in", row.name),
      x: 0,
      y: row.y,
      width: 1,
      height: 1,
      layoutOptions: { "elk.port.side": "WEST" },
    }));
    const outputs = item.shape.outputs.map((row) => ({
      id: portId(item.id, "out", row.name),
      x: item.width - 1,
      y: row.y,
      width: 1,
      height: 1,
      layoutOptions: { "elk.port.side": "EAST" },
    }));
    for (const port of [...inputs, ...outputs]) {
      ports.add(port.id);
    }
    return {
      id: item.id,
      width: item.width,
      height: item.height,
      layoutOptions: { "elk.portConstraints": "FIXED_POS" },
      ports: [...inputs, ...outputs],
    };
  });
  /** @type {Map<string, {id: string, sources: string[], targets: string[]}>} */
  const edges = new Map();
  for (const link of links) {
    if (!ids.has(link.from) || !ids.has(link.to) || link.from === link.to) {
      continue;
    }
    const source = portId(link.from, "out", link.sourcePort);
    const target = portId(link.to, "in", link.targetPort);
    const edge = {
      id: link.id,
      sources: [ports.has(source) ? source : link.from],
      targets: [ports.has(target) ? target : link.to],
    };
    edges.set(`${edge.sources[0]}>${edge.targets[0]}`, edge);
  }
  return { id: "level", layoutOptions: LAYOUT_OPTIONS, children, edges: [...edges.values()] };
}

/**
 * The ELK graph of a large level: nodes at their current place (the crossings
 * are reduced from their order), and one edge per linked pair of them.
 *
 * @param {{id: string, width: number, height: number, local?: {x: number, y: number}}[]} items
 * @param {{from: string, to: string}[]} links
 */
function largeElkGraph(items, links) {
  const ids = new Set(items.map((item) => item.id));
  const pairs = new Set();
  for (const link of links) {
    if (ids.has(link.from) && ids.has(link.to) && link.from !== link.to) {
      pairs.add(`${link.from}>${link.to}`);
    }
  }
  return {
    id: "level",
    layoutOptions: LARGE_LAYOUT_OPTIONS,
    children: items.map((item) => ({ id: item.id, width: item.width, height: item.height, x: item.local?.x ?? 0, y: item.local?.y ?? 0 })),
    edges: [...pairs].map((pair, index) => {
      const [from, to] = pair.split(">");
      return { id: `e${index}`, sources: [from], targets: [to] };
    }),
  };
}

/**
 * The layout positions from ELK's result, kept where the nodes were: the top-left
 * corner of their bounding box does not move.
 *
 * @param {{children?: {id: string, x?: number, y?: number}[]}} result
 * @param {{id: string, local: {x: number, y: number}}[]} items - The nodes laid out.
 * @returns {Record<string, {x: number, y: number}>}
 */
export function positionsFromElk(result, items) {
  const ids = new Set(items.map((item) => item.id));
  const laid = (result.children ?? []).filter((child) => ids.has(child.id));
  if (!laid.length) {
    return {};
  }
  const left = Math.min(...items.map((item) => item.local.x));
  const top = Math.min(...items.map((item) => item.local.y));
  const minX = Math.min(...laid.map((child) => child.x ?? 0));
  const minY = Math.min(...laid.map((child) => child.y ?? 0));
  return Object.fromEntries(
    laid.map((child) => [child.id, { x: Math.round(left + (child.x ?? 0) - minX), y: Math.round(top + (child.y ?? 0) - minY) }]),
  );
}

/**
 * The free place closest to a wished one for a new node, avoiding the others.
 *
 * @param {import("./geometry.js").Rect[]} rects - The nodes already there.
 * @param {{x: number, y: number}} wished
 * @param {{width: number, height: number}} size
 * @param {number} [margin]
 * @returns {{x: number, y: number}}
 */
export function freeSpot(rects, wished, size, margin = 30) {
  const overlaps = (/** @type {{x: number, y: number}} */ spot) =>
    rects.some(
      (rect) =>
        spot.x < rect.x + rect.width + margin &&
        spot.x + size.width + margin > rect.x &&
        spot.y < rect.y + rect.height + margin &&
        spot.y + size.height + margin > rect.y,
    );
  const step = { x: size.width + margin, y: 60 };
  // Rings of candidates around the wished place, nearest first.
  for (let ring = 0; ring < 20; ring += 1) {
    const candidates = [];
    for (let dx = -ring; dx <= ring; dx += 1) {
      for (let dy = -ring; dy <= ring; dy += 1) {
        if (Math.max(Math.abs(dx), Math.abs(dy)) === ring) {
          candidates.push({ x: wished.x + dx * step.x, y: wished.y + dy * step.y });
        }
      }
    }
    candidates.sort((a, b) => Math.hypot(a.x - wished.x, a.y - wished.y) - Math.hypot(b.x - wished.x, b.y - wished.y));
    const found = candidates.find((spot) => !overlaps(spot));
    if (found) {
      return found;
    }
  }
  return wished;
}
