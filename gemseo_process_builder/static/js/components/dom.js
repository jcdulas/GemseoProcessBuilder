// @ts-check
// Small helpers to build DOM elements without a framework.

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

/** Stroke paths of the toolbar icons, drawn in a 16×16 box. */
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
};

/**
 * Create a toolbar icon.
 *
 * @param {keyof typeof ICON_PATHS} name
 * @returns {SVGSVGElement}
 */
export function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.classList.add("icon");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICON_PATHS[name]);
  svg.append(path);
  return svg;
}
