// @ts-check
// Small helpers to build DOM elements without a framework.
import { NODE_ICON_PATHS, nodeAppearance } from "../lib/node_icons.js";

/**
 * Create an element.
 *
 * @param {string} tag - Tag name, optionally with classes: "button.button.primary".
 * @param {Record<string, any>} [attributes] - Attributes; `on*` keys add event
 *   listeners, `text` sets the text content, `dataset` sets data attributes.
 * @param {(Node | string | null | undefined | false)[]} [children]
 * @returns {HTMLElement}
 */
export function el(tag, attributes = {}, children = []) {
  const [name, ...classes] = tag.split(".");
  const element = document.createElement(name);
  if (classes.length) {
    element.classList.add(...classes);
  }
  for (const [key, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) {
      continue;
    }
    if (key === "text") {
      element.textContent = String(value);
    } else if (key === "dataset") {
      Object.assign(element.dataset, value);
    } else if (key.startsWith("on") && typeof value === "function") {
      element.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) {
      element.setAttribute(key, "");
    } else {
      element.setAttribute(key, String(value));
    }
  }
  for (const child of children) {
    if (child !== null && child !== undefined && child !== false) {
      element.append(child);
    }
  }
  return element;
}

/** Stroke paths of the interface icons, drawn in a 16×16 box. */
const ICON_PATHS = {
  new: "M4 1.5h5.5l3 3v10h-8.5z M9.5 1.5v3h3",
  open: "M1.5 4v9.5h12l1.5-6.5h-12l-1.5 6.5 M1.5 4h4l1.5 1.5h6v1.5",
  save: "M2 2h10l2 2v10h-12z M5 2v4h6v-4 M4.5 14v-5h7v5",
  undo: "M5 3.5l-3 3 3 3 M2 6.5h7a4 4 0 0 1 0 8h-2",
  redo: "M11 3.5l3 3-3 3 M14 6.5h-7a4 4 0 0 0 0 8h2",
  validate: "M2.5 8.5l3.5 3.5 7.5-8",
  run: "M4 2.5v11l9-5.5z",
  stop: "M3.5 3.5h9v9h-9z",
  layout: "M1.5 2.5h4v3h-4z M10.5 2.5h4v3h-4z M6 10.5h4v3h-4z M3.5 5.5v2.5h9v-2.5 M8 8v2.5",
  fit: "M1.5 5.5v-4h4 M10.5 1.5h4v4 M14.5 10.5v4h-4 M5.5 14.5h-4v-4",
  search: "M7 2.5a4.5 4.5 0 1 0 0 9a4.5 4.5 0 1 0 0-9z M10.5 10.5l4 4",
  menu: "M2.5 4h11 M2.5 8h11 M2.5 12h11",
  nodes: "M2 2.5h5v5h-5z M9 2.5h5v5h-5z M2 9.5h5v5h-5z M11.5 9.5v5 M9 12h5",
  tree: "M3 2.5v11 M3 5h4.5 M3 11h4.5 M9 3h5v4h-5z M9 9h5v4h-5z",
  problems: "M8 2l6.5 11.5h-13z M8 6.5v3 M8 11.8h.01",
  runs: "M2.5 8a5.5 5.5 0 1 0 1.6-3.9 M2 2.5V5h2.5 M8 5v3l2 1.5",
  console: "M2 3h12v10H2z M4.5 6.5l2 1.5-2 1.5 M8 10h3.5",
  settings: "M2.5 4.5h6 M11.5 4.5h2 M10 3v3 M2.5 11.5h2 M7.5 11.5h6 M6 10v3",
  help: "M8 1.5a6.5 6.5 0 1 0 0 13a6.5 6.5 0 1 0 0-13z M6 6.2a2 2 0 1 1 2.7 1.9c-.5.2-.7.6-.7 1.1v.5 M8 11.6h.01",
  zoomIn: "M7 2.5a4.5 4.5 0 1 0 0 9a4.5 4.5 0 1 0 0-9z M10.5 10.5l4 4 M5 7h4 M7 5v4",
  zoomOut: "M7 2.5a4.5 4.5 0 1 0 0 9a4.5 4.5 0 1 0 0-9z M10.5 10.5l4 4 M5 7h4",
  plus: "M8 3v10 M3 8h10",
  close: "M4 4l8 8 M12 4l-8 8",
  success: "M8 1.5a6.5 6.5 0 1 0 0 13a6.5 6.5 0 1 0 0-13z M5.2 8.2l1.9 1.9 3.7-4",
  failure: "M8 1.5a6.5 6.5 0 1 0 0 13a6.5 6.5 0 1 0 0-13z M8 4.8v3.8 M8 11h.01",
  chevronDown: "M4 6l4 4 4-4",
  refresh: "M13.5 8a5.5 5.5 0 1 1-1.6-3.9 M14 2v3h-3",
  results: "M2.5 13.5h11 M4.5 11V8 M7.5 11V4.5 M10.5 11V6.5",
};

/**
 * Create an interface icon.
 *
 * @param {keyof typeof ICON_PATHS} name
 * @returns {SVGSVGElement}
 */
export function icon(name) {
  return pathIcon(ICON_PATHS[name], 16);
}

/**
 * Create the icon of a kind of node (see `lib/node_icons.js`).
 *
 * @param {{type: string, kind?: string}} node
 * @returns {HTMLElement} A tile colored by the type of the node.
 */
export function nodeIconTile(node) {
  const appearance = nodeAppearance(node);
  return el(`span.node-tile.tone-${appearance.tone}`, {}, [pathIcon(NODE_ICON_PATHS[appearance.icon], 24)]);
}

/**
 * An SVG icon made of one stroked path.
 *
 * @param {string} d
 * @param {number} size - The size of the box the path is drawn in.
 * @returns {SVGSVGElement}
 */
function pathIcon(d, size) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
  svg.classList.add("icon");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", d);
  svg.append(path);
  return svg;
}
