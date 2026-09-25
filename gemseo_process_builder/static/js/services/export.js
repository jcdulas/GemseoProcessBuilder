// @ts-check
// Image export of the views (SPEC § 13): SVG with the styles written on the
// elements, or PNG rendered by the page at 1×, 2× or 4×.
//
// Each view gives a source: a function returning its standalone SVG. File ›
// Export › Image… exports the view of the active center tab; results charts
// also have a context menu.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";
import { openContextMenu } from "../components/context_menu.js";
import { openModal } from "../components/modal.js";
import { STYLE_PROPERTIES, fitViewBox, pngSize, serializeTree, standaloneSvg } from "../lib/svg_export.js";

const SVG_NS = "http://www.w3.org/2000/svg";
/** The pages whose SVG elements are charts. */
const CHARTS = ".results-page";
const TEXT_TAGS = new Set(["text", "tspan", "title"]);

/**
 * @typedef {object} Picture
 * @property {string} svg - A standalone SVG document.
 * @property {number} width
 * @property {number} height
 */

/**
 * @typedef {object} ImageSource
 * @property {string} name - The suggested file name, without extension.
 * @property {(options: {full: boolean}) => Promise<Picture>} produce
 * @property {boolean} [fullChoice] - Offer "current level" or "whole model".
 */

/** @type {Map<string, ImageSource>} - By center tab id. */
const sources = new Map();

/**
 * Let File › Export › Image… export the view of a center tab.
 *
 * @param {string} tabId
 * @param {ImageSource} source
 */
export function registerImageSource(tabId, source) {
  sources.set(tabId, source);
}

/**
 * The tree of an SVG element with the computed styles of its elements.
 *
 * @param {Element} element
 * @param {(element: Element) => boolean} skip
 * @returns {import("../lib/svg_export.js").SvgTree | null}
 */
function treeOf(element, skip) {
  if (element.namespaceURI !== SVG_NS || skip(element)) {
    return null;
  }
  const computed = getComputedStyle(element);
  if (computed.display === "none") {
    return null;
  }
  /** @type {Record<string, string>} */
  const style = {};
  for (const property of STYLE_PROPERTIES) {
    style[property] = computed.getPropertyValue(property);
  }
  /** @type {Record<string, string>} */
  const attributes = {};
  for (const attribute of element.attributes) {
    attributes[attribute.name] = attribute.value;
  }
  const children = [...element.children].map((child) => treeOf(child, skip)).filter((child) => child !== null);
  const text = TEXT_TAGS.has(element.localName) && !element.children.length ? (element.textContent ?? "") : undefined;
  return { tag: element.localName, attributes, style, children: /** @type {any[]} */ (children), text };
}

/**
 * A standalone SVG of the content of an SVG element, fitted to its content.
 *
 * @param {SVGSVGElement} svg - In the document, so that its styles are computed.
 * @param {{title?: string, skip?: (element: Element) => boolean, margin?: number}} [options]
 *   ``skip`` leaves out elements of the page only (backgrounds, selections).
 * @returns {Picture}
 */
export function pictureOf(svg, { title = "", skip = () => false, margin = 16 } = {}) {
  const box = fitViewBox(svg.getBBox(), margin);
  const content = [...svg.children]
    .map((child) => treeOf(child, skip))
    .filter((tree) => tree !== null)
    .map((tree) => serializeTree(/** @type {any} */ (tree)))
    .join("");
  return { svg: standaloneSvg(content, box, { title }), width: box.width, height: box.height };
}

/**
 * Render an SVG document to a PNG, in the page.
 *
 * @param {Picture} picture
 * @param {number} scale
 * @returns {Promise<string>} The PNG, base64-encoded.
 */
export async function pngOf(picture, scale) {
  const size = pngSize(picture.width, picture.height, scale);
  const url = URL.createObjectURL(new Blob([picture.svg], { type: "image/svg+xml" }));
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = size.width;
    canvas.height = size.height;
    const context = /** @type {CanvasRenderingContext2D} */ (canvas.getContext("2d"));
    context.drawImage(image, 0, 0, size.width, size.height);
    return canvas.toDataURL("image/png").split(",")[1];
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * Ask the format of an image.
 *
 * @param {boolean} fullChoice
 * @returns {Promise<{format: "svg" | "png", scale: number, full: boolean} | null>}
 */
function askFormat(fullChoice) {
  return new Promise((resolve) => {
    const format = /** @type {HTMLSelectElement} */ (
      el("select.select", {}, [el("option", { value: "svg", text: "SVG (vector, editable in Inkscape)" }), el("option", { value: "png", text: "PNG (image)" })])
    );
    const scale = /** @type {HTMLSelectElement} */ (
      el("select.select", {}, [1, 2, 4].map((value) => el("option", { value: String(value), text: `${value}×` })))
    );
    scale.value = "2";
    const content = /** @type {HTMLSelectElement} */ (
      el("select.select", {}, [el("option", { value: "level", text: "The level shown" }), el("option", { value: "full", text: "The whole model, containers expanded" })])
    );
    const scaleRow = el("label.form-row", {}, [el("span.form-label", { text: "Scale" }), scale]);
    const sync = () => (scaleRow.hidden = format.value !== "png");
    format.addEventListener("change", sync);
    sync();
    let answer = /** @type {any} */ (null);
    openModal({
      title: "Export image",
      body: el("div.export-form", {}, [
        el("label.form-row", {}, [el("span.form-label", { text: "Format" }), format]),
        scaleRow,
        fullChoice ? el("label.form-row", {}, [el("span.form-label", { text: "Content" }), content]) : null,
      ]),
      buttons: [
        { label: "Cancel" },
        {
          label: "Export…",
          primary: true,
          onClick: () => {
            answer = { format: format.value, scale: Number(scale.value), full: content.value === "full" };
          },
        },
      ],
      onClose: () => resolve(answer),
    });
  });
}

/**
 * Export an image: ask its format and file, then write it.
 *
 * @param {ImageSource} source
 */
export async function exportImage(source) {
  const choice = await askFormat(Boolean(source.fullChoice));
  if (!choice) {
    return;
  }
  try {
    const picture = await source.produce({ full: choice.full });
    const extension = choice.format;
    const path = await app.api.call(
      "dialog.saveFile",
      {
        title: "Export image",
        filter: extension === "svg" ? "SVG images (*.svg)" : "PNG images (*.png)",
        start: `${source.name}${choice.full ? "_full" : ""}.${extension}`,
      },
      { timeout: 24 * 3600 * 1000 },
    );
    if (!path) {
      return;
    }
    const data = extension === "svg" ? picture.svg : await pngOf(picture, choice.scale);
    const saved = await app.api.call("image.export", { path, format: extension, data });
    console.info(`Image exported to ${saved}`);
  } catch (error) {
    showError("The image could not be exported", error);
  }
}

/**
 * The source of any SVG of the page (a results chart).
 *
 * @param {SVGSVGElement} svg
 * @param {string} name
 * @returns {ImageSource}
 */
export function elementSource(svg, name) {
  return { name, produce: async () => pictureOf(svg, { title: svg.getAttribute("aria-label") ?? "", margin: 4 }) };
}

/** A file name from a title. */
export function fileStem(/** @type {string} */ title) {
  return title.replace(/[^\w.-]+/g, "_").replace(/^_+|_+$/g, "") || "image";
}

export function installImageExport() {
  app.actions.handle("file.exportImage", {
    run: () => {
      const tab = app.tabs.center.active ?? "";
      const source = sources.get(tab);
      if (source) {
        exportImage(source);
        return;
      }
      // Results tabs and wizards: the first chart shown.
      const svg = /** @type {SVGSVGElement | null} */ (app.tabs.center.page(tab)?.querySelector(`${CHARTS}:not([hidden]) svg`));
      if (svg) {
        exportImage(elementSource(svg, fileStem(`${tab}_${svg.getAttribute("aria-label") ?? "chart"}`)));
      } else {
        showError("Nothing to export", new Error("The active tab shows no diagram or chart."));
      }
    },
  });
  // Every chart of the results can be exported from its context menu.
  document.addEventListener("contextmenu", (event) => {
    const target = /** @type {Element} */ (event.target);
    const svg = target.closest?.("svg");
    if (!(svg instanceof SVGSVGElement) || !svg.closest(CHARTS)) {
      return;
    }
    event.preventDefault();
    openContextMenu(event.clientX, event.clientY, [
      { label: "Export image…", run: () => exportImage(elementSource(svg, fileStem(svg.getAttribute("aria-label") ?? "chart"))) },
    ]);
  });
}
