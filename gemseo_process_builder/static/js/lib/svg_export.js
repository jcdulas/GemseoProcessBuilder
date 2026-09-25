// @ts-check
// Standalone SVG files from the SVG of a view (SPEC § 13): the styles the page
// gives through its CSS are written on each element, the viewBox is fitted to
// the content and a white background is added, so that the file looks the same
// in a browser, in Inkscape or rendered to PNG.
//
// Pure: the page reads the elements and their computed styles into a tree of
// plain objects (services/export.js); this module turns the tree into text.

/**
 * @typedef {object} SvgTree
 * @property {string} tag
 * @property {Record<string, string>} attributes
 * @property {Record<string, string>} [style] - Computed style of the element.
 * @property {SvgTree[]} children
 * @property {string} [text] - Text content (text elements without children).
 */

/** The CSS properties written on the elements: those our stylesheets use on SVG. */
export const STYLE_PROPERTIES = [
  "fill",
  "fill-opacity",
  "stroke",
  "stroke-width",
  "stroke-opacity",
  "stroke-dasharray",
  "stroke-linecap",
  "stroke-linejoin",
  "opacity",
  "font-family",
  "font-size",
  "font-weight",
  "font-style",
  "text-anchor",
  "dominant-baseline",
  "visibility",
];

/** Values that need not be written: the SVG defaults. */
const DEFAULTS = {
  "fill-opacity": "1",
  "stroke-opacity": "1",
  "stroke-dasharray": "none",
  "stroke-linecap": "butt",
  "stroke-linejoin": "miter",
  opacity: "1",
  "font-style": "normal",
  "font-weight": "400",
  "text-anchor": "start",
  "dominant-baseline": "auto",
  visibility: "visible",
};

/** Properties that only matter on text. */
const TEXT_PROPERTIES = new Set(["font-family", "font-size", "font-weight", "font-style", "text-anchor", "dominant-baseline"]);
const TEXT_TAGS = new Set(["text", "tspan", "textPath"]);

/** Attributes of the page that mean nothing in a file. */
const DROPPED_ATTRIBUTES = new Set(["class", "style", "tabindex", "role", "aria-label", "data-id"]);

/** Fonts every system has, after the fonts of the page. */
const FALLBACK_FONTS = "Arial, Helvetica, sans-serif";

/**
 * The style attribute of an element from its computed style.
 *
 * @param {string} tag
 * @param {Record<string, string>} computed
 * @returns {string}
 */
export function styleAttribute(tag, computed) {
  const declarations = [];
  for (const property of STYLE_PROPERTIES) {
    let value = computed[property];
    if (!value || value === DEFAULTS[/** @type {keyof DEFAULTS} */ (property)]) {
      continue;
    }
    if (TEXT_PROPERTIES.has(property) && !TEXT_TAGS.has(tag)) {
      continue;
    }
    if (property === "font-family" && !/sans-serif|serif|monospace/.test(value)) {
      value = `${value}, ${FALLBACK_FONTS}`;
    }
    declarations.push(`${property}:${value.replace(/"/g, "'")}`);
  }
  return declarations.join(";");
}

/** @param {string} text */
export function escapeXml(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/**
 * The SVG text of a tree, with the styles written on the elements.
 *
 * @param {SvgTree} tree
 * @returns {string}
 */
export function serializeTree(tree) {
  const attributes = Object.entries(tree.attributes).filter(([name]) => !DROPPED_ATTRIBUTES.has(name) && !name.startsWith("on"));
  const style = tree.style ? styleAttribute(tree.tag, tree.style) : "";
  if (style) {
    attributes.push(["style", style]);
  }
  const head = [tree.tag, ...attributes.map(([name, value]) => `${name}="${escapeXml(value)}"`)].join(" ");
  const inner = tree.children.length ? tree.children.map(serializeTree).join("") : escapeXml(tree.text ?? "");
  return inner ? `<${head}>${inner}</${tree.tag}>` : `<${head}/>`;
}

/**
 * A box around content, with a margin, rounded outwards to whole units.
 *
 * @param {{x: number, y: number, width: number, height: number}} box
 * @param {number} [margin]
 * @returns {{x: number, y: number, width: number, height: number}}
 */
export function fitViewBox(box, margin = 16) {
  const x = Math.floor(box.x - margin);
  const y = Math.floor(box.y - margin);
  return {
    x,
    y,
    width: Math.ceil(box.x + box.width + margin) - x,
    height: Math.ceil(box.y + box.height + margin) - y,
  };
}

/**
 * A standalone SVG document: namespace, fitted viewBox, background, content.
 *
 * @param {string} content - Serialized elements.
 * @param {{x: number, y: number, width: number, height: number}} box - The viewBox.
 * @param {{background?: string, title?: string}} [options]
 * @returns {string}
 */
export function standaloneSvg(content, box, { background = "#ffffff", title = "" } = {}) {
  const { x, y, width, height } = box;
  return [
    '<?xml version="1.0" encoding="UTF-8"?>\n',
    `<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="${width}" height="${height}" viewBox="${x} ${y} ${width} ${height}">`,
    title ? `<title>${escapeXml(title)}</title>` : "",
    background ? `<rect x="${x}" y="${y}" width="${width}" height="${height}" fill="${background}"/>` : "",
    content,
    "</svg>\n",
  ].join("");
}

/** The largest side of a PNG, in pixels (browsers draw nothing beyond). */
export const MAX_PNG_SIDE = 16384;

/**
 * The size of a PNG at a scale, reduced if it would be too large.
 *
 * @param {number} width
 * @param {number} height
 * @param {number} scale
 * @returns {{width: number, height: number, scale: number}}
 */
export function pngSize(width, height, scale) {
  const fitted = Math.min(scale, MAX_PNG_SIDE / Math.max(width, height, 1));
  return { width: Math.round(width * fitted), height: Math.round(height * fitted), scale: fitted };
}
