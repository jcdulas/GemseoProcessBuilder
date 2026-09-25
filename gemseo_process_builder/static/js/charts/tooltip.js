// @ts-check
// A floating tooltip shared by the charts.
import { el } from "../components/dom.js";

/** @type {HTMLElement | null} */
let element = null;

/**
 * Show lines of text next to the pointer.
 *
 * @param {number} x - Client coordinates of the pointer.
 * @param {number} y
 * @param {(string | {text: string, color?: string})[]} lines
 */
export function showTooltip(x, y, lines) {
  element ??= document.body.appendChild(el("div.chart-tooltip"));
  element.replaceChildren(
    ...lines.map((line) => {
      const { text, color } = typeof line === "string" ? { text: line, color: undefined } : line;
      const row = el("div", {}, [color ? el("span.chart-swatch") : null, text]);
      const swatch = /** @type {HTMLElement | null} */ (row.querySelector(".chart-swatch"));
      if (swatch && color) {
        swatch.style.background = color;
      }
      return row;
    }),
  );
  element.hidden = false;
  // Keep the tooltip inside the window.
  const box = element.getBoundingClientRect();
  const left = x + 14 + box.width > window.innerWidth ? x - 14 - box.width : x + 14;
  const top = Math.min(y + 12, window.innerHeight - box.height - 4);
  element.style.left = `${Math.max(4, left)}px`;
  element.style.top = `${Math.max(4, top)}px`;
}

export function hideTooltip() {
  if (element) {
    element.hidden = true;
  }
}
