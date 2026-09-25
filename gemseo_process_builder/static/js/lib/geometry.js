// @ts-check
// Geometry of the workflow canvas: node sizes, port anchors, link paths, fitting.

export const NODE_WIDTH = 200;
export const HEADER_HEIGHT = 26;
export const PORT_ROW_HEIGHT = 18;
export const BODY_PADDING = 6;
export const CONTAINER_PADDING = 24;
export const COLLAPSED_BODY_HEIGHT = 24;
/** Height of the body of a card: a node whose variables are counted, not listed. */
export const CARD_BODY_HEIGHT = 30;
export const CHAR_WIDTH = 6.6;
/** Default spacing when placing nodes that have no position yet. */
export const GRID_STEP = { x: 260, y: 160 };

/**
 * @typedef {object} Rect
 * @property {number} x
 * @property {number} y
 * @property {number} width
 * @property {number} height
 */

/**
 * @typedef {object} PortRow
 * @property {string} name
 * @property {number} y - Center of the row, relative to the node's top.
 */

/**
 * @typedef {object} NodeShape
 * @property {number} width
 * @property {number} height
 * @property {PortRow[]} inputs - Shown input ports, anchored at x = 0.
 * @property {PortRow[]} outputs - Shown output ports, anchored at x = width.
 * @property {number} hidden - Ports not shown.
 * @property {{inputs: number, outputs: number}} [card] - For a card: its
 *   variables, counted. Links attach to the middle of its sides.
 */

/**
 * Which ports a node shows, given its display mode.
 *
 * @param {{local_name: string, direction: string}[]} ports
 * @param {"all" | "connected" | "none" | "compact"} mode
 * @param {Set<string>} connected - "in:name" / "out:name" keys of connected ports.
 * @returns {{inputs: string[], outputs: string[], hidden: number}}
 */
export function visiblePorts(ports, mode, connected) {
  const shown = ports.filter((port) => {
    if (mode === "none" || mode === "compact") {
      return false;
    }
    return mode === "all" || connected.has(`${port.direction}:${port.local_name}`);
  });
  return {
    inputs: shown.filter((port) => port.direction === "in").map((port) => port.local_name),
    outputs: shown.filter((port) => port.direction === "out").map((port) => port.local_name),
    hidden: ports.length - shown.length,
  };
}

/**
 * Size and port rows of a component, or of a collapsed container.
 *
 * @param {{inputs: string[], outputs: string[], hidden: number}} ports
 * @returns {NodeShape}
 */
export function nodeShape({ inputs, outputs, hidden }) {
  const rows = Math.max(inputs.length, outputs.length);
  const bodyHeight =
    rows === 0 && hidden === 0
      ? COLLAPSED_BODY_HEIGHT
      : rows * PORT_ROW_HEIGHT + (hidden ? PORT_ROW_HEIGHT : 0) + 2 * BODY_PADDING;
  /** @param {string[]} names */
  const toRows = (names) =>
    names.map((name, index) => ({
      name,
      y: HEADER_HEIGHT + BODY_PADDING + index * PORT_ROW_HEIGHT + PORT_ROW_HEIGHT / 2,
    }));
  return {
    width: NODE_WIDTH,
    height: HEADER_HEIGHT + bodyHeight,
    inputs: toRows(inputs),
    outputs: toRows(outputs),
    hidden,
  };
}

/**
 * The shape of a card: a node drawn with its name, its kind and the count of
 * its variables, linked by one point on each side (like n8n).
 *
 * @param {{inputs: number, outputs: number}} counts
 * @returns {NodeShape}
 */
export function cardShape(counts) {
  return {
    width: NODE_WIDTH,
    height: HEADER_HEIGHT + CARD_BODY_HEIGHT,
    inputs: [],
    outputs: [],
    hidden: counts.inputs + counts.outputs,
    card: counts,
  };
}

/**
 * Where links attach to a card: the middle of its side.
 *
 * @param {Rect} rect
 * @param {"in" | "out"} direction
 * @returns {{x: number, y: number}}
 */
export function cardAnchor(rect, direction) {
  return { x: rect.x + (direction === "in" ? 0 : rect.width), y: rect.y + rect.height / 2 };
}

/**
 * Where a port connects, in canvas coordinates.
 *
 * @param {{x: number, y: number}} origin - Top-left corner of the node.
 * @param {NodeShape} shape
 * @param {"in" | "out"} direction
 * @param {string} name
 * @returns {{x: number, y: number} | null} Null when the port is not shown.
 */
export function portAnchor(origin, shape, direction, name) {
  const rows = direction === "in" ? shape.inputs : shape.outputs;
  const row = rows.find((candidate) => candidate.name === name);
  if (!row) {
    return null;
  }
  return { x: origin.x + (direction === "in" ? 0 : shape.width), y: origin.y + row.y };
}

/**
 * Where links attach to a node whose port is hidden: the middle of its side.
 *
 * @param {Rect} rect
 * @param {"in" | "out"} direction
 * @returns {{x: number, y: number}}
 */
export function sideAnchor(rect, direction) {
  return {
    x: rect.x + (direction === "in" ? 0 : rect.width),
    y: rect.y + Math.min(rect.height / 2, HEADER_HEIGHT / 2),
  };
}

/**
 * A horizontal cubic Bézier from an output to an input.
 *
 * @param {{x: number, y: number}} start
 * @param {{x: number, y: number}} end
 * @returns {string} An SVG path.
 */
export function linkPath(start, end) {
  const handle = Math.max(40, Math.abs(end.x - start.x) / 2);
  return `M${start.x},${start.y} C${start.x + handle},${start.y} ${end.x - handle},${end.y} ${end.x},${end.y}`;
}

/**
 * The smallest rectangle containing all the rectangles.
 *
 * @param {Rect[]} rects
 * @returns {Rect | null}
 */
export function boundingBox(rects) {
  if (!rects.length) {
    return null;
  }
  const left = Math.min(...rects.map((rect) => rect.x));
  const top = Math.min(...rects.map((rect) => rect.y));
  const right = Math.max(...rects.map((rect) => rect.x + rect.width));
  const bottom = Math.max(...rects.map((rect) => rect.y + rect.height));
  return { x: left, y: top, width: right - left, height: bottom - top };
}

/**
 * The zoom transform showing a box in a viewport.
 *
 * @param {Rect | null} box
 * @param {{width: number, height: number}} viewport
 * @param {{padding?: number, maxScale?: number}} [options]
 * @returns {{x: number, y: number, k: number}}
 */
export function fitTransform(box, viewport, { padding = 40, maxScale = 1.5 } = {}) {
  if (!box || viewport.width <= 0 || viewport.height <= 0) {
    return { x: 0, y: 0, k: 1 };
  }
  const k = Math.min(
    maxScale,
    (viewport.width - 2 * padding) / Math.max(box.width, 1),
    (viewport.height - 2 * padding) / Math.max(box.height, 1),
  );
  const scale = Math.max(k, 0.05);
  return {
    x: viewport.width / 2 - scale * (box.x + box.width / 2),
    y: viewport.height / 2 - scale * (box.y + box.height / 2),
    k: scale,
  };
}

/**
 * A free position for the n-th node without a stored position.
 *
 * @param {number} index
 * @param {number} [columns]
 * @returns {{x: number, y: number}}
 */
export function gridPosition(index, columns = 4) {
  return {
    x: 40 + (index % columns) * GRID_STEP.x,
    y: 40 + Math.floor(index / columns) * GRID_STEP.y,
  };
}

/**
 * Shorten a label to fit a width, with an ellipsis.
 *
 * @param {string} text
 * @param {number} width
 * @returns {string}
 */
export function fitText(text, width) {
  const max = Math.max(1, Math.floor(width / CHAR_WIDTH));
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}
