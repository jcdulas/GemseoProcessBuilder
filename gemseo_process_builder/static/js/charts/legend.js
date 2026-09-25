// @ts-check
// Legends of the charts, as HTML next to the SVG.
import { el } from "../components/dom.js";

/**
 * A legend: one swatch and label per series.
 *
 * @param {{label: string, color: string, dashed?: boolean}[]} items
 * @returns {HTMLElement}
 */
export function legend(items) {
  return el(
    "div.chart-legend",
    {},
    items.map((item) => {
      const swatch = el(`span.chart-swatch${item.dashed ? ".dashed" : ""}`);
      swatch.style.background = item.dashed ? "transparent" : item.color;
      swatch.style.borderColor = item.color;
      return el("span.chart-legend-item", {}, [swatch, item.label]);
    }),
  );
}
